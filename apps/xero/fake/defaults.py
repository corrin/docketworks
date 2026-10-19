"""What Xero fills in on an object the application did not spell out.

Every value here is read off a recording in ``recordings/`` — the file is
named beside each block — and ``tests/test_defaults.py`` asserts each key is
one that recording carries, so a default that Xero stopped sending, or one
this file invented, fails a test rather than shipping in a body.
"""

from apps.xero.fake.wire import Json

# recordings/organisation.json: the fake's own name in every envelope, so a
# log line or an error body that reached a person says where it came from.
PROVIDER_NAME = "Docketworks fake Xero"

# recordings/contact.json — Xero returns a created contact with the four
# phone slots and the two address slots present and empty.
CONTACT: dict[str, Json] = {
    "ContactStatus": "ACTIVE",
    "Addresses": [{"AddressType": "POBOX"}, {"AddressType": "STREET"}],
    "Phones": [
        {"PhoneType": "DDI"},
        {"PhoneType": "DEFAULT"},
        {"PhoneType": "FAX"},
        {"PhoneType": "MOBILE"},
    ],
    "ContactGroups": [],
    "IsSupplier": False,
    "IsCustomer": False,
    "ContactPersons": [],
    "HasAttachments": False,
    "Attachments": [],
    "HasValidationErrors": False,
}

# recordings/invoice.json
INVOICE: dict[str, Json] = {
    "Type": "ACCREC",
    "Status": "DRAFT",
    "LineAmountTypes": "Exclusive",
    "CreditNotes": [],
    "Prepayments": [],
    "Overpayments": [],
    "AmountPaid": 0,
    "AmountCredited": 0,
    "SentToContact": False,
    "CurrencyRate": 1,
    "IsDiscounted": False,
    "HasAttachments": False,
    "HasErrors": False,
    "Attachments": [],
    "InvoicePaymentServices": [],
}

# recordings/quote.json
QUOTE: dict[str, Json] = {
    "Status": "DRAFT",
    "LineAmountTypes": "EXCLUSIVE",
    "CurrencyRate": 1,
    "Terms": "",
}

# recordings/purchase_order.json
PURCHASE_ORDER: dict[str, Json] = {
    "Type": "PURCHASEORDER",
    "Status": "DRAFT",
    "LineAmountTypes": "Exclusive",
    "CurrencyRate": 1,
    "HasErrors": False,
    "IsDiscounted": False,
    "SentToContact": False,
    "HasAttachments": False,
    "Attachments": [],
}

# recordings/invoice.json, first line item: a line always carries its
# tracking list, empty when nothing is tracked.
LINE_ITEM: dict[str, Json] = {"Tracking": []}

# Xero's first number for a new organisation, by document kind: the
# sequence the store continues from when it holds nothing of the kind.
FIRST_NUMBER = {"invoice": "INV-0001", "quote": "QU-0001", "purchase_order": "PO-0001"}

# ---- Payroll NZ: what Xero fills in on the employees phase's writes ----------

# recordings/employee_create.json. No startDate or payrollCalendarID: Xero
# ignores a start date sent on the create and sets both from the employment.
EMPLOYEE: dict[str, Json] = {
    "otherGivenNames": None,
    "gender": None,
    "phoneNumber": None,
    "startDate": None,
    "payrollCalendarID": None,
    "engagementType": None,
    "fixedTermEndDate": None,
    "endDate": None,
    "employmentType": "Employee",
    "jobTitle": None,
}
# recordings/employee_create.json, its address.
EMPLOYEE_ADDRESS: dict[str, Json] = {"addressLine2": None, "suburb": None}

# recordings/salary_and_wage_create.json
SALARY_AND_WAGE: dict[str, Json] = {"workPatternType": "DaysAndHours"}

# recordings/employee_tax_update.json
EMPLOYEE_TAX: dict[str, Json] = {
    "hasSpecialStudentLoanRate": False,
    "specialStudentLoanRatePercentage": None,
    "specialTaxRatePercentage": None,
    "kiwiSaverStatus": "ActiveKiwiSaverMember",
    "kiwiSaverOptOutDate": None,
    "kiwiSaverContributionHolidayEndDate": None,
    "hasStudentLoanBalance": False,
    "studentLoanBalance": None,
    "studentLoanAsAt": None,
    "registeredForGST": None,
}

# recordings/payment_method_create.json, each bank account.
BANK_ACCOUNT: dict[str, Json] = {
    "particulars": None,
    "code": None,
    "dollarAmount": None,
    "reference": "",
}

# recordings/leave_setup_create.json
LEAVE_SETUP: dict[str, Json] = {
    "negativeAnnualLeaveBalancePaidAmount": None,
    "sickLeaveScheduleOfAccrual": "AnnuallyAfter6Months",
    "sickLeaveAnniversaryDate": None,
    "annualLeaveAnniversaryDate": None,
}

# recordings/employee_leave_type_create.json: a leave type assigned with no
# accrual rule of its own.
EMPLOYEE_LEAVE_TYPE: dict[str, Json] = {
    "hoursAccruedAnnually": 0.0,
    "unitsAccruedAnnually": 0.0,
    "maximumToAccrue": 0.0,
    "rateAccruedHourly": None,
    "percentageOfGrossEarnings": 0.0,
    "includeHolidayPayEveryPay": None,
    "showAnnualLeaveInAdvance": None,
    "annualLeaveTotalAmountPaid": None,
    "scheduleOfAccrualDate": None,
}

# recordings/employee_leave_types.json, read straight after the leave setup:
# the three leave types it assigns, by name, and the rule each accrues by.
# The balances and the sick accrual come from the setup's own fields.
HOLIDAY_PAY = "Holiday Pay"
ANNUAL_LEAVE = "Annual Leave"
SICK_LEAVE = "Sick Leave"
LEAVE_SETUP_ASSIGNS: dict[str, dict[str, Json]] = {
    HOLIDAY_PAY: {
        "scheduleOfAccrual": "PercentageOfGrossEarnings",
        "percentageOfGrossEarnings": 8.0,
        "showAnnualLeaveInAdvance": None,
    },
    ANNUAL_LEAVE: {
        "scheduleOfAccrual": "OnAnniversaryDate",
        "percentageOfGrossEarnings": 0.0,
        "includeHolidayPayEveryPay": None,
        "showAnnualLeaveInAdvance": True,
    },
    SICK_LEAVE: {
        "scheduleOfAccrual": "AnnuallyAfter6Months",
        "percentageOfGrossEarnings": 0.0,
        "includeHolidayPayEveryPay": None,
        "showAnnualLeaveInAdvance": None,
    },
}
