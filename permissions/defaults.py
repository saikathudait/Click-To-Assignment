DEFAULT_PERMISSIONS = [
    ('create_job', 'Create Job', 'Allow creating new job requests.'),
    ('view_own_jobs', 'View Own Jobs', 'View jobs created or assigned to the user.'),
    ('view_all_jobs', 'View All Jobs', 'View every job in the system.'),
    ('approve_job', 'Approve Jobs', 'Approve work submissions and AI outputs.'),
    ('manage_forms', 'Manage Forms', 'Access Form Management and edit fields.'),
    ('manage_users', 'Manage Users', 'View and edit user accounts.'),
    ('manage_holidays', 'Manage Holidays', 'Add/update holiday calendar.'),
    ('manage_menu', 'Manage Menu & Permissions', 'Control visibility of menus and permissions.'),
    ('manage_permissions', 'Permission Management', 'Adjust role permissions.'),
    ('view_assigned_forms', 'View Assigned Forms', 'See forms assigned specifically to the user.'),
]

ROLE_DEFAULTS = {
    'MARKETING': {
        'create_job',
        'view_own_jobs',
        'view_assigned_forms',
    },
    'SUPERADMIN': 'ALL',
}
