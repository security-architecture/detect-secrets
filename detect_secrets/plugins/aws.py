"""
This plugin searches for AWS key IDs
"""
from __future__ import absolute_import

import hashlib
import hmac
import re
import string
import textwrap
from datetime import datetime

import requests

from .base import RegexBasedDetector
from detect_secrets.core.constants import VerifiedResult


class AWSKeyDetector(RegexBasedDetector):

    secret_type = 'AWS Access Key'

    denylist = (
        re.compile(r'AKIA[0-9A-Z]{16}'),
    )

    def verify(self, token, content):
        secret_access_key_candidates = get_secret_access_keys(content)
        if not secret_access_key_candidates:
            return VerifiedResult.UNVERIFIED

        for candidate in secret_access_key_candidates:
            if verify_aws_secret_access_key(token, candidate):
                return VerifiedResult.VERIFIED_TRUE

        return VerifiedResult.VERIFIED_FALSE


def get_secret_access_keys(content):
    # AWS secret access keys are 40 characters long.
    regex = re.compile(
        r'= *([\'"]?)([%s]{40})(\1)$' % (
            string.ascii_letters + string.digits + '+/='
        ),
    )

    return [
        match[1]
        for line in content.splitlines()
        for match in regex.findall(line)
    ]


def verify_aws_secret_access_key(key, secret):  # pragma: no cover
    """
    Using requests, because we don't want to require boto3 for this one
    optional verification step.

    Loosely based off:
    https://docs.aws.amazon.com/general/latest/gr/sigv4-signed-request-examples.html

    :type key: str
    :type secret: str
    """
    now = datetime.utcnow()
    amazon_datetime = now.strftime('%Y%m%dT%H%M%SZ')

    headers = {
        # This is a required header for the signing process
        'Host': 'sts.amazonaws.com',
        'X-Amz-Date': amazon_datetime,
    }
    body = {
        'Action': 'GetCallerIdentity',
        'Version': '2011-06-15',
    }

    # Step #1: Canonical Request
    signed_headers = ';'.join(
        map(
            lambda x: x.lower(),
            headers.keys(),
        ),
    )
    canonical_request = textwrap.dedent("""
        POST
        /

        {headers}

        {signed_headers}
        {hashed_payload}
    """)[1:-1].format(

        headers='\n'.join([
            '{}:{}'.format(header.lower(), value)
            for header, value in headers.items()
        ]),
        signed_headers=signed_headers,

        # Poor man's method, but works for this use case.
        hashed_payload=hashlib.sha256(
            '&'.join([
                '{}={}'.format(header, value)
                for header, value in body.items()
            ]).encode('utf-8'),
        ).hexdigest(),
    )

    # Step #2: String to Sign
    region = 'us-east-1'
    scope = '{request_date}/{region}/sts/aws4_request'.format(
        request_date=now.strftime('%Y%m%d'),

        # STS is a global service; this is just for latency control.
        region=region,
    )

    string_to_sign = textwrap.dedent("""
        AWS4-HMAC-SHA256
        {request_datetime}
        {scope}
        {hashed_canonical_request}
    """)[1:-1].format(
        request_datetime=amazon_datetime,
        scope=scope,
        hashed_canonical_request=hashlib.sha256(
            canonical_request.encode('utf-8'),
        ).hexdigest(),
    )

    # Step #3: Calculate signature
    signing_key = _sign(
        _sign(
            _sign(
                _sign(
                    'AWS4{}'.format(secret).encode('utf-8'),
                    now.strftime('%Y%m%d'),
                ),
                region,
            ),
            'sts',
        ),
        'aws4_request',
    )

    signature = _sign(
        signing_key,
        string_to_sign,
        hex=True,
    )

    # Step #4: Add to request headers
    headers['Authorization'] = (
        'AWS4-HMAC-SHA256 '
        'Credential={access_key}/{scope}, '
        'SignedHeaders={signed_headers}, '
        'Signature={signature}'
    ).format(
        access_key=key,
        scope=scope,
        signed_headers=signed_headers,
        signature=signature,
    )

    # Step #5: Finally send the request
    response = requests.post(
        'https://sts.amazonaws.com',
        headers=headers,
        data=body,
    )

    if response.status_code == 403:
        return False

    return True


def _sign(key, message, hex=False):  # pragma: no cover
    value = hmac.new(key, message.encode('utf-8'), hashlib.sha256)
    if not hex:
        return value.digest()

    return value.hexdigest()
