from django import forms
from django.contrib.auth import password_validation

from .models import User


class RegistrationForm(forms.Form):
    name = forms.CharField(label="Vor- und Nachname", max_length=150, widget=forms.TextInput(attrs={"autocomplete": "name"}))
    email = forms.EmailField(
        label="Studentische E-Mail-Adresse",
        widget=forms.EmailInput(attrs={"autocomplete": "email", "placeholder": "vorname.nachname@uni-…de"}),
    )
    password1 = forms.CharField(
        label="Passwort",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
        help_text="Mindestens 8 Zeichen, nicht nur Zahlen.",
    )
    password2 = forms.CharField(
        label="Passwort wiederholen", strip=False, widget=forms.PasswordInput(attrs={"autocomplete": "new-password"})
    )
    accept_terms = forms.BooleanField(
        label="Ich akzeptiere die Nutzungsbedingungen und habe die Datenschutzerklärung gelesen."
    )

    def __init__(self, *args, site=None, **kwargs):
        self.site = site
        super().__init__(*args, **kwargs)
        domains = site.domain_list if site else []
        if domains:
            self.fields["email"].help_text = "Erlaubt sind Adressen von: " + ", ".join(domains)

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if self.site and not self.site.email_domain_allowed(email):
            raise forms.ValidationError(
                "Bitte verwende deine studentische E-Mail-Adresse der Universität."
            )
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError(
                "Für diese Adresse gibt es bereits ein Konto. Melde dich an oder setze dein Passwort zurück."
            )
        return email

    def clean(self):
        data = super().clean()
        p1, p2 = data.get("password1"), data.get("password2")
        if p1 and p2 and p1 != p2:
            self.add_error("password2", "Die Passwörter stimmen nicht überein.")
        elif p1:
            probe = User(email=data.get("email", ""), name=data.get("name", ""))
            try:
                password_validation.validate_password(p1, probe)
            except forms.ValidationError as error:
                self.add_error("password1", error)
        return data


class LoginForm(forms.Form):
    email = forms.EmailField(label="E-Mail-Adresse", widget=forms.EmailInput(attrs={"autocomplete": "email", "autofocus": True}))
    password = forms.CharField(label="Passwort", strip=False, widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}))


class EmailForm(forms.Form):
    email = forms.EmailField(label="E-Mail-Adresse", widget=forms.EmailInput(attrs={"autocomplete": "email", "autofocus": True}))


class ProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["name"]


class DeleteAccountForm(forms.Form):
    password = forms.CharField(label="Zur Bestätigung: dein Passwort", strip=False, widget=forms.PasswordInput)

    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_password(self):
        password = self.cleaned_data["password"]
        if not self.user.check_password(password):
            raise forms.ValidationError("Das Passwort ist nicht korrekt.")
        return password
