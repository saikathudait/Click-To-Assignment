import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.getenv('SECRET_KEY', 'django-insecure-default-key-change-this')
DEBUG = os.getenv('DEBUG', 'True') == 'True'
ALLOWED_HOSTS = os.getenv('ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',')

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.humanize',
    'django.contrib.sites',
    
    # Custom apps
    'accounts.apps.AccountsConfig',
    'jobs',
    'profiles',
    'approvals',
    'ai_pipeline',
    'auditlog',
    'marketing',
    'customer',
    'superadmin',
    'tickets',
    'holidays',
    'form_management',
    'permissions',
    'notifications',
    # Third-party auth
    'allauth',
    'allauth.account',
    'allauth.socialaccount',
    'allauth.socialaccount.providers.google',
]

FORM_MANAGEMENT_FORM_MODULES = [
    'accounts.forms',
    'jobs.forms',
    'tickets.forms',
    'marketing.forms',
    'profiles.forms',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'auditlog.middleware.AuditLogMiddleware',
    'superadmin.middleware.ErrorCodeLoggingMiddleware',
    'accounts.middleware.CleanOrphanSocialAccountsMiddleware',
]

ROOT_URLCONF = 'click_to_assignment.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'django.template.context_processors.media',
                'permissions.context_processors.role_permissions',
                'notifications.context_processors.notifications_data',
                'profiles.context_processors.user_avatar',
            ],
        },
    },
]

WSGI_APPLICATION = 'click_to_assignment.wsgi.application'


# MONGO_DB_NAME = os.getenv('MONGO_DB_NAME', 'click_to_assignment')
# MONGO_HOST = os.getenv('MONGO_HOST', 'localhost')
# MONGO_PORT = int(os.getenv('MONGO_PORT', 27017))
# MONGO_USER = os.getenv('MONGO_USER', '')
# MONGO_PASSWORD = os.getenv('MONGO_PASSWORD', '')



# Build CLIENT dict safely
# mongo_client_config = {
#     'host': MONGO_HOST,
#     'port': MONGO_PORT,
# }

MONGO_URI = os.getenv('MONGO_URI')
MONGO_DB_NAME = os.getenv('MONGO_DB_NAME', 'commonvideogeneration_db')


# MongoDB Configuration
# DATABASES = {
#     'default': {
#         'ENGINE': 'djongo',
#         'NAME': MONGO_DB_NAME,
#         'ENFORCE_SCHEMA': False,
#         'CLIENT': mongo_client_config,
#     }
# }

DATABASES = {
    'default': {
        'ENGINE': 'djongo',
        'NAME': MONGO_DB_NAME,
        'CLIENT': {
            'host': MONGO_URI,
        }
    }
}



# Custom User Model
AUTH_USER_MODEL = 'accounts.User'

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator', 'OPTIONS': {'min_length': 8}},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
    {'NAME': 'accounts.validators.SymbolValidator'},
]

# Internationalization
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Asia/Kolkata'
USE_I18N = True
USE_L10N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / 'static']

# Media files
MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')

# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Login/Logout URLs
LOGIN_URL = '/accounts/login/'
LOGIN_REDIRECT_URL = '/accounts/post-login/'
LOGOUT_REDIRECT_URL = '/accounts/login/'
SITE_ID = 1

# Authentication backends
AUTHENTICATION_BACKENDS = (
    'django.contrib.auth.backends.ModelBackend',
    'allauth.account.auth_backends.AuthenticationBackend',
)

# Allauth settings
ACCOUNT_AUTHENTICATION_METHOD = 'email'
ACCOUNT_EMAIL_REQUIRED = True
ACCOUNT_USERNAME_REQUIRED = False
ACCOUNT_USER_MODEL_USERNAME_FIELD = None
ACCOUNT_PRESERVE_USERNAME_CLAIM = False
ACCOUNT_EMAIL_VERIFICATION = 'none'
SOCIALACCOUNT_ADAPTER = 'accounts.adapters.CustomerSocialAccountAdapter'
SOCIALACCOUNT_EMAIL_VERIFICATION = 'none'
SOCIALACCOUNT_AUTO_SIGNUP = True
SOCIALACCOUNT_PROVIDERS = {
    'google': {
        'SCOPE': ['profile', 'email'],
        'APP': {
            'client_id': os.getenv('GOOGLE_CLIENT_ID', ''),
            'secret': os.getenv('GOOGLE_CLIENT_SECRET', ''),
            'key': ''
        }
    }
}

# File Upload Settings
MAX_UPLOAD_SIZE = int(os.getenv('MAX_UPLOAD_SIZE', 52428800))
ALLOWED_UPLOAD_EXTENSIONS = ['doc', 'docx', 'pdf', 'png', 'jpg', 'jpeg', 'pptx', 'csv', 'xlsx', 'xls']

# Email Configuration
EMAIL_BACKEND = os.getenv('EMAIL_BACKEND', 'django.core.mail.backends.console.EmailBackend')
EMAIL_HOST = os.getenv('EMAIL_HOST', 'smtp.gmail.com')
EMAIL_PORT = int(os.getenv('EMAIL_PORT', 587))
EMAIL_USE_TLS = os.getenv('EMAIL_USE_TLS', 'True') == 'True'
EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD', '')

# AI API Configuration
# OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
ANTHROPIC_API_KEY = os.getenv('ANTHROPIC_API_KEY')
OPAL_API_KEY = os.getenv('OPAL_API_KEY')
#OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')

# Session Settings
SESSION_COOKIE_AGE = 86400  # 24 hours
SESSION_SAVE_EVERY_REQUEST = True


if not DEBUG:
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_BROWSER_XSS_FILTER = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = 'DENY'
    
    
# Ensure media directories exist
os.makedirs(os.path.join(MEDIA_ROOT, 'attachments'), exist_ok=True)
os.makedirs(os.path.join(MEDIA_ROOT, 'profile_pictures'), exist_ok=True)
os.makedirs(os.path.join(MEDIA_ROOT, 'reports'), exist_ok=True)
os.makedirs(os.path.join(MEDIA_ROOT, 'content/final'), exist_ok=True)


# OpenAI configuration
OPENAI_MODEL_SUMMARY = 'gpt-5.1'
OPENAI_MODEL_STRUCTURE = 'gpt-5.1'
OPENAI_MODEL_CONTENT = 'gpt-5.1'
OPENAI_MODEL_REFERENCES = 'gpt-5.1'
OPENAI_MODEL_FINAL = 'gpt-5.1'

# Prompts directory
PROMPTS_DIR = os.path.join(BASE_DIR, 'prompts')



