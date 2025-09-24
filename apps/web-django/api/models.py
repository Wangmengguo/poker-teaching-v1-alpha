from django.db import models


class Replay(models.Model):
    hand_id = models.CharField(max_length=64, unique=True)
    payload = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return self.hand_id


class Session(models.Model):
    session_id = models.CharField(max_length=64, unique=True)
    config = models.JSONField(default=dict)  # SB/BB/init_stack 等
    stacks = models.JSONField(default=list)  # [p0, p1]
    button = models.IntegerField(default=0)  # 0 or 1
    hand_counter = models.IntegerField(default=1)
    status = models.CharField(max_length=16, default="running")
    ended_reason = models.CharField(max_length=16, null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    stats = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Session({self.session_id})"
