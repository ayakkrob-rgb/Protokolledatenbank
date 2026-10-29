from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.db import models
from django.utils import timezone


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email, password, **extra):
        if not email:
            raise ValueError("Eine E-Mail-Adresse ist erforderlich.")
        email = self.normalize_email(email).lower()
        user = self.model(email=email, **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra):
        extra.setdefault("is_staff", False)
        extra.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra)

    def create_superuser(self, email, password=None, **extra):
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        extra.setdefault("email_verified", True)
        return self._create_user(email, password, **extra)

    def get_by_natural_key(self, username):
        return self.get(email__iexact=username)


class User(AbstractBaseUser, PermissionsMixin):
    email = models.EmailField("E-Mail-Adresse", unique=True)
    name = models.CharField("Name", max_length=150)
    email_verified = models.BooleanField("E-Mail bestätigt", default=False)
    is_active = models.BooleanField(
        "Aktiv", default=True, help_text="Deaktivierte (gesperrte) Konten können sich nicht anmelden."
    )
    is_staff = models.BooleanField("Admin", default=False, help_text="Hat Zugriff auf die Verwaltung.")
    date_joined = models.DateTimeField("Registriert am", default=timezone.now)
    verified_at = models.DateTimeField("Bestätigt am", null=True, blank=True)
    admin_note = models.TextField("Interne Notiz", blank=True)

    objects = UserManager()

    USERNAME_FIELD = "email"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS = ["name"]

    class Meta:
        ordering = ["-date_joined"]
        verbose_name = "Nutzer"
        verbose_name_plural = "Nutzer"

    def __str__(self):
        return f"{self.name} <{self.email}>" if self.name else self.email

    def save(self, *args, **kwargs):
        self.email = (self.email or "").strip().lower()
        super().save(*args, **kwargs)

    def get_full_name(self):
        return self.name or self.email

    def get_short_name(self):
        return (self.name or self.email).split(" ")[0]

    @property
    def first_name(self):
        return self.get_short_name()

    def mark_verified(self):
        self.email_verified = True
        self.verified_at = timezone.now()
        self.save(update_fields=["email_verified", "verified_at"])
