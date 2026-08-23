from django.core.management.base import BaseCommand

from accounts.models import CustomUser


class Command(BaseCommand):
    help = "Create default superuser and operator accounts if they don't exist."

    def handle(self, *args, **options):
        if not CustomUser.objects.filter(username="admin").exists():
            CustomUser.objects.create_superuser(
                username="admin",
                email="admin@intelliflow.local",
                password="admin123",
                role="admin",
            )
            self.stdout.write(self.style.SUCCESS("Created admin user (admin/admin123)"))
        else:
            self.stdout.write("Admin user already exists.")

        if not CustomUser.objects.filter(username="operator").exists():
            CustomUser.objects.create_user(
                username="operator",
                email="operator@intelliflow.local",
                password="operator123",
                role="operator",
            )
            self.stdout.write(self.style.SUCCESS("Created operator user (operator/operator123)"))
        else:
            self.stdout.write("Operator user already exists.")
