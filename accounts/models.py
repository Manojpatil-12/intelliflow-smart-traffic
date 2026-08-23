from django.contrib.auth.models import AbstractUser
from django.db import models


class CustomUser(AbstractUser):
    ROLE_CHOICES = [
        ("admin", "Admin"),
        ("operator", "Operator"),
    ]
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default="operator")

    class Meta:
        verbose_name = "User"
        verbose_name_plural = "Users"

    def __str__(self):
        return f"{self.username} ({self.role})"

    @property
    def is_admin_role(self):
        return self.role == "admin"

    @property
    def is_operator_role(self):
        return self.role == "operator"
