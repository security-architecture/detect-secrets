"""
This plugin searches for Stripe keys
"""
from __future__ import absolute_import

import re
from base64 import b64encode

import requests

from .base import RegexBasedDetector
from detect_secrets.core.constants import VerifiedResult


class StripeDetector(RegexBasedDetector):

    secret_type = 'Stripe Access Key'

    denylist = (
        # Stripe standard keys begin with sk_live and restricted with rk_live
        re.compile(r'(?:r|s)k_live_[0-9a-zA-Z]{24}'),
    )

    def verify(self, token, **kwargs):  # pragma: no cover
        response = requests.get(
            'https://api.stripe.com/v1/charges',
            headers={
                'Authorization': b'Basic ' + b64encode(
                    '{}:'.format(token).encode('utf-8'),
                ),
            },
        )

        if response.status_code == 200:
            return VerifiedResult.VERIFIED_TRUE

        # Restricted keys may be limited to certain endpoints
        if token.startswith('rk_live'):
            return VerifiedResult.UNVERIFIED

        return VerifiedResult.VERIFIED_FALSE
