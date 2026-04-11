from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("houses", "0002_alter_user_role"),
    ]

    operations = [
        migrations.AddField(
            model_name="stayagreement",
            name="status",
            field=models.CharField(default="pending", max_length=20),
        ),
        migrations.AddField(
            model_name="stayagreement",
            name="sitter_signed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="stayagreement",
            name="owner_signed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]

