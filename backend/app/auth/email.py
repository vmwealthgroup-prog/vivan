"""
VM ALGO — Email sending abstraction
=======================================
NOT wired to a real mail provider. Doing that needs real SMTP/SES/SendGrid
credentials this environment doesn't have and can't verify end-to-end — so
rather than fake it, ConsoleEmailSender logs the message (verification
links, reset links) to stdout, which is exactly what you need for local dev
and for manually testing the flow before wiring a provider.

Before production: implement a second EmailSender (e.g. SESEmailSender)
against this same interface and swap it in app/auth/routes.py's
`get_email_sender()` dependency. Nothing else in the auth module needs to
change — that's the point of the abstraction.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

logger = logging.getLogger("vmalgo.email")


class EmailSender(ABC):
    @abstractmethod
    def send(self, to: str, subject: str, body: str) -> None:
        ...


class ConsoleEmailSender(EmailSender):
    def send(self, to: str, subject: str, body: str) -> None:
        logger.info("=== EMAIL (dev/console sender — not actually delivered) ===")
        logger.info("To: %s", to)
        logger.info("Subject: %s", subject)
        logger.info("%s", body)
        logger.info("=== END EMAIL ===")


def get_email_sender() -> EmailSender:
    return ConsoleEmailSender()
