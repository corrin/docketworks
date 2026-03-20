"""Constants used by the Xero API integration."""

XERO_SCOPES = [
    "offline_access",
    "openid",
    "profile",
    "email",
    "accounting.contacts",
    "accounting.invoices",
    "accounting.attachments",
    "accounting.settings",
    "accounting.journals.read",
    # "accounting.inventory",  # REMOVED - invalid scope, use accounting.settings instead
    "projects",
    "payroll.timesheets",
    "payroll.payruns",
    "payroll.payslip",
    "payroll.employees",
    "payroll.settings",
]
