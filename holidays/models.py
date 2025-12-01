from django.conf import settings
from django.db import models


class Holiday(models.Model):
    HOLIDAY_TYPE_SINGLE = 'SINGLE'
    HOLIDAY_TYPE_RANGE = 'RANGE'
    HOLIDAY_TYPE_CHOICES = [
        (HOLIDAY_TYPE_SINGLE, 'Single Day'),
        (HOLIDAY_TYPE_RANGE, 'Date Range'),
    ]

    TEAM_ALL = 'ALL'
    TEAM_MARKETING = 'MARKETING'
    TEAM_SUPERADMIN = 'SUPERADMIN'

    TEAM_CHOICES = [
        (TEAM_MARKETING, 'Marketing Team'),
        (TEAM_SUPERADMIN, 'Super Admin'),
    ]

    title = models.CharField(max_length=255)
    holiday_type = models.CharField(max_length=10, choices=HOLIDAY_TYPE_CHOICES, default=HOLIDAY_TYPE_SINGLE)
    start_date = models.DateField()
    end_date = models.DateField()
    applies_to = models.CharField(
        max_length=255,
        default=TEAM_ALL,
        help_text='Comma separated list of teams (MARKETING,SUPERADMIN) or ALL'
    )
    notes = models.TextField(blank=True, null=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_holidays'
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-start_date']

    def __str__(self):
        return self.title

    def applies_to_list(self):
        if not self.applies_to or self.applies_to == self.TEAM_ALL:
            return ['All Teams']
        mapping = dict(self.TEAM_CHOICES)
        return [mapping.get(item, item) for item in self.applies_to.split(',') if item]
