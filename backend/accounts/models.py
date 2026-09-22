from django.conf import settings
from django.db import models

from geodata.models import Campsite


class SavedCampsite(models.Model):
    """A user bookmarking a campsite. Foundation for trip planning later."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="saved_campsites",
    )
    campsite = models.ForeignKey(
        Campsite,
        on_delete=models.CASCADE,
        related_name="saved_by",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "campsite"], name="unique_saved_campsite")
        ]
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user} saved {self.campsite}"
