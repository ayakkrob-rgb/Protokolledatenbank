import os

from django.core.management.base import BaseCommand, CommandError

from accounts.models import User


class Command(BaseCommand):
    help = "Legt ein Admin-Konto an, falls es noch nicht existiert (Werte aus ADMIN_EMAIL/ADMIN_PASSWORD oder Argumenten)."

    def add_arguments(self, parser):
        parser.add_argument("--email", default=os.environ.get("ADMIN_EMAIL", ""))
        parser.add_argument("--password", default=os.environ.get("ADMIN_PASSWORD", ""))
        parser.add_argument("--name", default="Fachschaft Admin")

    def handle(self, *args, **options):
        email = (options["email"] or "").strip().lower()
        password = options["password"]
        if not email:
            self.stdout.write("ADMIN_EMAIL nicht gesetzt – kein Admin-Konto angelegt.")
            return
        user = User.objects.filter(email__iexact=email).first()
        if user:
            if not user.is_staff:
                user.is_staff = user.is_superuser = True
                user.email_verified = True
                user.save()
                self.stdout.write(self.style.SUCCESS(f"{email} ist jetzt Admin."))
            else:
                self.stdout.write(f"Admin {email} existiert bereits.")
            return
        if not password:
            raise CommandError("Für ein neues Admin-Konto wird ADMIN_PASSWORD bzw. --password benötigt.")
        User.objects.create_superuser(email=email, password=password, name=options["name"])
        self.stdout.write(self.style.SUCCESS(f"Admin-Konto {email} angelegt."))
