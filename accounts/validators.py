from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _
import re

class SymbolValidator:
    def validate(self, password, user=None):
        if not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
            raise ValidationError(
                _("Password must contain at least one special character."),
                code='password_no_symbol',
            )
    
    def get_help_text(self):
        return _("Your password must contain at least one special character.")

def validate_whatsapp_number(value):
    """Validate WhatsApp number format (10 digits after country code)"""
    if not re.match(r'^\d{10}$', value):
        raise ValidationError('WhatsApp number must be exactly 10 digits.')

def validate_name_length(value, field_name="Name"):
    """Validate name has minimum 25 characters"""
    if len(value) > 25:
        raise ValidationError(f'{field_name} must be at least 25 characters long.')
    
    
class PasswordComplexityValidator:
    """
    Validates that the password contains:
    - At least one letter
    - At least one number
    - At least one special character
    """
    
    def validate(self, password, user=None):
        if not re.search(r'[A-Za-z]', password):
            raise ValidationError(
                _("Password must contain at least one letter."),
                code='password_no_letter',
            )
        if not re.search(r'\d', password):
            raise ValidationError(
                _("Password must contain at least one number."),
                code='password_no_number',
            )
        if not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
            raise ValidationError(
                _("Password must contain at least one special character."),
                code='password_no_special',
            )
    
    def get_help_text(self):
        return _(
            "Your password must contain at least one letter, one number, "
            "and one special character (!@#$%^&*(),.?\":{}|<>)."
        )