from datetime import timezone
from django.db import models
from click_to_assignment import settings
from jobs.models import Job
from accounts.models import User
from django.utils import timezone 


class JobSummary(models.Model):
    job = models.OneToOneField(Job, on_delete=models.CASCADE, related_name='jobsummary')
    topic = models.CharField(max_length=500)
    word_count = models.IntegerField(default=1500)
    reference_style = models.CharField(max_length=50, default='Harvard')
    writing_style = models.CharField(max_length=100, default='Report')
    summary_text = models.TextField()
    
    generated_at = models.DateTimeField(auto_now_add=True)
    #generation_count = models.IntegerField(default=0)
    regeneration_count = models.IntegerField(default=0)
    is_approved = models.BooleanField(default=False)
    approved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='approved_summaries')
    approved_at = models.DateTimeField(null=True, blank=True)
    
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'job_summaries'
        verbose_name_plural = 'Job Summaries'
    
    def __str__(self):
        return f"Summary for {self.job.job_id}"
    
    def can_regenerate(self):
        """Allow up to 3 generations (0,1,2)."""
        return (self.regeneration_count or 0) < 3
    
    

class JobStructure(models.Model):
    job = models.OneToOneField(Job, on_delete=models.CASCADE, related_name='structure')
    structure_text = models.TextField()
    total_word_count = models.IntegerField(default=1500)
    
    sections = models.PositiveIntegerField(default=1500)
    
    generated_at = models.DateTimeField(auto_now_add=True)
    regeneration_count = models.IntegerField(default=0)
    is_approved = models.BooleanField(default=False)
    approved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='approved_structures')
    approved_at = models.DateTimeField(null=True, blank=True)
    
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'job_structures'
    
    def __str__(self):
        return f"Structure for {self.job.job_id}"
    
    def can_regenerate(self):
        """Check if can regenerate (max 3 times)"""
        return (self.regeneration_count or 0) < 3
    
    

class GeneratedContent(models.Model):
    job = models.OneToOneField(Job, on_delete=models.CASCADE, related_name='content')
    content_text = models.TextField()
    
    actual_word_count = models.IntegerField(default=1500)
    
    generated_at = models.DateTimeField(auto_now_add=True)
    regeneration_count = models.IntegerField(default=0)
    is_approved = models.BooleanField(default=False)
    approved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='approved_contents')
    approved_at = models.DateTimeField(null=True, blank=True)
    
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'generated_contents'
    
    def __str__(self):
        return f"Content for {self.job.job_id}"
    
    def can_regenerate(self):
        """Check if can regenerate (max 3 times)"""
        return (self.regeneration_count or 0) < 3

class References(models.Model):
    job = models.OneToOneField(Job, on_delete=models.CASCADE, related_name='references')
    reference_list = models.TextField()
    citation_list = models.TextField()
    total_references = models.PositiveIntegerField(default=10)
    
    generated_at = models.DateTimeField(auto_now_add=True)
    regeneration_count = models.IntegerField(default=0)
    is_approved = models.BooleanField(default=False)
    approved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='approved_references')
    approved_at = models.DateTimeField(null=True, blank=True)
    
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'references'
        verbose_name_plural = 'References'
    
    def __str__(self):
        return f"References for {self.job.job_id}"
    
    def can_regenerate(self):
        """Check if can regenerate (max 3 times)"""
        return (self.regeneration_count or 0) < 3

class FullContent(models.Model):
    job = models.OneToOneField(Job, on_delete=models.CASCADE, related_name='full_content')
    content_with_citations = models.TextField()
    final_word_count = models.PositiveIntegerField(null=True, blank=True)
    content_file = models.FileField(upload_to='content/final/', null=True, blank=True)
    
    generated_at = models.DateTimeField(auto_now_add=True)
    regeneration_count = models.IntegerField(default=0)
    is_approved = models.BooleanField(default=False)
    approved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='approved_full_contents')
    approved_at = models.DateTimeField(null=True, blank=True)
    
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'full_contents'
    
    def __str__(self):
        return f"Full Content for {self.job.job_id}"
    
    def can_regenerate(self):
        """Check if can regenerate (max 3 times)"""
        return (self.regeneration_count or 0) < 3

class PlagiarismReport(models.Model):
    job = models.OneToOneField(Job, on_delete=models.CASCADE, related_name='plag_report')
    report_data = models.TextField()
    similarity_percentage = models.FloatField(default=0.0)
    
    
    report_file = models.FileField(upload_to='reports/plagiarism/', null=True, blank=True)
    
    # Generation tracking
    generated_at = models.DateTimeField(auto_now_add=True)
    generation_count = models.IntegerField(default=0)
    is_approved = models.BooleanField(default=False)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='approved_plag_reports'
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    
    
    
    class Meta:
        db_table = 'plagiarism_reports'
        
    def __str__(self):
        return f"Plagiarism Report for {self.job.job_id}"
    
    def can_regenerate(self):
        """Check if can regenerate (max 3 times)"""
        return (self.generation_count or 0) < 3

class AIReport(models.Model):
    job = models.OneToOneField(Job, on_delete=models.CASCADE, related_name='ai_report')
    report_data = models.TextField()
    ai_percentage = models.FloatField(default=0.0)
    
    generated_at = models.DateTimeField(auto_now_add=True)
    report_file = models.FileField(upload_to='reports/ai/', null=True, blank=True)
    
    # Generation tracking
    generation_count = models.IntegerField(default=0)
    is_approved = models.BooleanField(default=False)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='approved_ai_reports'
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'ai_reports'
    
    def __str__(self):
        return f"AI Report for {self.job.job_id}"
    
    def can_regenerate(self):
        """Check if can regenerate (max 3 times)"""
        return (self.generation_count or 0) < 3
