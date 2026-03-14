---
title: Manage Staff
---

# Manage Staff

> **When to use:** You need to add a new team member, update someone's details, or change their permissions.

## What You'll Need

- [ ] Superuser access (only superusers can manage staff)
- [ ] The new person's details (name, email, wage rate)

## Steps

### 1. Open Staff Management

Navigate to **Admin > Staff** (you need to be a superuser to see this).

<!-- PLACEHOLDER: Screenshot showing the Staff Management page with the staff table -->

You'll see a table listing all staff members with their name, role (Office Staff / SuperUser), last login, and date joined.

### 2. Add a new staff member

Click **New Staff** to open the staff form. It has three tabs:

#### Personal Info

<!-- PLACEHOLDER: Screenshot showing the Personal Info tab of the staff form -->

- **First Name** and **Last Name** -- as you'd expect.
- **Preferred Name** -- what they go by day-to-day (optional).
- **Email** -- their login email. Must be unique.
- **Password** -- at least 8 characters. They can change it later.
- **Base Wage Rate** -- their hourly wage in NZD. This is used for job costing calculations.
- **Xero User ID** -- links them to their Xero profile for payroll (optional).
- **Profile Icon** -- click the avatar to upload a photo.

#### Working Hours

<!-- PLACEHOLDER: Screenshot showing the Working Hours tab -->

Set the scheduled hours for each day of the week (Monday through Sunday). Enter in quarter-hour increments (0.25, 0.5, etc.). These are used in the timesheet summary to show whether a full day has been entered.

#### Permissions

- **Is Office Staff** -- tick this for office-based staff. It controls which navbar items they see (office staff see everything; non-office staff see a simplified view focused on their own time entry).
- **Is SuperUser** -- tick this for people who need admin access (staff management, system settings, etc.).

### 3. Edit an existing staff member

Click the **Edit** button next to any staff member in the table. The same form opens, pre-filled with their current details. You can change anything except their email.

### 4. Remove a staff member

Click the **Delete** button next to their name. You'll be asked to confirm before anything happens.

## What Happens Next

- New staff members can log in immediately with their email and password
- Their wage rate feeds into job costing whenever they enter time
- Their scheduled hours appear in the timesheet summary for checking daily totals
- If linked to Xero, their payroll data can be reconciled using the [Payroll report](/admin/run-payroll)

## Tips

::: tip
Set up working hours accurately -- they're used to check whether a full day of time has been entered. If someone works 7.5 hours and the system expects 8, it'll flag every day as incomplete.
:::

::: warning
Be careful with the SuperUser permission. SuperUsers can see everything and manage all settings. Only give this to people who genuinely need it.
:::
