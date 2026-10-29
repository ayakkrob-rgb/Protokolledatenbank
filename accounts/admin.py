from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.forms import BaseUserCreationForm, UserChangeForm

from .models import User


class UserCreateForm(BaseUserCreationForm):
    class Meta:
        model = User
        fields = ("email", "name")


class UserEditForm(UserChangeForm):
    class Meta:
        model = User
        fields = "__all__"


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    form = UserEditForm
    add_form = UserCreateForm
    ordering = ["-date_joined"]
    list_display = ["email", "name", "email_verified", "is_staff", "is_active", "date_joined"]
    list_filter = ["email_verified", "is_staff", "is_active"]
    search_fields = ["email", "name"]
    fieldsets = (
        (None, {"fields": ("email", "name", "password")}),
        ("Status", {"fields": ("email_verified", "verified_at", "is_active", "is_staff", "is_superuser")}),
        ("Sonstiges", {"fields": ("admin_note", "date_joined", "last_login")}),
    )
    add_fieldsets = ((None, {"classes": ("wide",), "fields": ("email", "name", "password1", "password2")}),)
    filter_horizontal = ()
