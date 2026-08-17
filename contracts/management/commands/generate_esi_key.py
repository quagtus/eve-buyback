"""Print a Fernet key for ESI_TOKEN_KEY.

A command rather than a line in the README: the key has an exact format, and
telling operators to run a python one-liner invites a wrong one.
"""

from cryptography.fernet import Fernet
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Generate a key for ESI_TOKEN_KEY, which encrypts the stored refresh token."

    def handle(self, *args, **options):
        self.stdout.write(Fernet.generate_key().decode())
