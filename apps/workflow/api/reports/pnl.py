from datetime import datetime, timedelta

from dateutil.relativedelta import relativedelta
from django.db.models import Sum
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.workflow.models import XeroJournalLineItem


class CompanyProfitAndLossReport(APIView):
    EQUITY_MOVEMENT_ACCOUNTS = {
        "Opening Stock",
        "Opening Stock - Work in Progress",
        "Closing Stock",
        "Closing Stock - Work in Progress",
        "Amortisation",
    }

    def categorize_transaction(
        self, account_name, account_type, total, report, compare_periods, period_index
    ):
        if account_name in self.EQUITY_MOVEMENT_ACCOUNTS:
            category = "Equity Movements"
        elif account_type == "AccountType.REVENUE":
            category = "Trading Income"
        elif account_type in ["AccountType.EXPENSE", "AccountType.OVERHEADS"]:
            category = "Operating Expenses"
        elif account_type == "AccountType.DIRECTCOSTS":
            category = "Cost of Sales"
        else:
            category = "Other Items"

        if account_name not in report[category]:
            report[category][account_name] = [0] * (compare_periods + 1)

        report[category][account_name][period_index] += total

    def rollup_line_items(self, period_start, period_end):
        """
        Roll up line items for all document types into a single dictionary.
        """
        journal_rollup = (
            XeroJournalLineItem.objects.filter(
                journal__journal_date__range=[period_start, period_end]
            )
            .values("account__account_type", "account__account_name")
            .annotate(total=Sum("net_amount"))
        )

        consolidated_rollup = {}
        for item in journal_rollup:
            key = (item["account__account_type"], item["account__account_name"])
            consolidated_rollup[key] = consolidated_rollup.get(key, 0) + item["total"]

        return consolidated_rollup

    def calculate_totals(self, report, compare_periods, period_index):
        """
        Calculate totals for sales, COGS, gross profit, operating expenses,
        equity movements, and profits.
        """
        total_sales = sum(
            report["Trading Income"].get(account, [0])[period_index]
            for account in report["Trading Income"]
        )
        total_cogs = sum(
            report["Cost of Sales"].get(account, [0])[period_index]
            for account in report["Cost of Sales"]
        )
        gross_profit = total_sales - total_cogs
        total_expenses = sum(
            report["Operating Expenses"].get(account, [0])[period_index]
            for account in report["Operating Expenses"]
        )
        total_equity_movements = sum(
            report["Equity Movements"].get(account, [0])[period_index]
            for account in report["Equity Movements"]
        )
        net_profit = gross_profit - total_expenses
        accounting_profit = net_profit - total_equity_movements

        return {
            "Trading Income": total_sales,
            "Cost of Sales": total_cogs,
            "Gross Profit": gross_profit,
            "Operating Expenses": total_expenses,
            "Net Profit": net_profit,
            "Equity Movements": total_equity_movements,
            "Accounting Profit": accounting_profit,
        }

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="start_date",
                type=str,
                required=True,
                description="Period start date (YYYY-MM-DD)",
            ),
            OpenApiParameter(
                name="end_date",
                type=str,
                required=True,
                description="Period end date (YYYY-MM-DD)",
            ),
            OpenApiParameter(
                name="compare",
                type=int,
                required=False,
                description="Number of comparison periods to include. Defaults to 0.",
            ),
            OpenApiParameter(
                name="period_type",
                type=str,
                required=False,
                enum=["month", "year"],
                description="Period type for comparison. Defaults to 'month'.",
            ),
        ],
        responses={200: OpenApiTypes.OBJECT},
    )
    def get(self, request):
        start_date = datetime.strptime(
            request.query_params.get("start_date"), "%Y-%m-%d"
        )
        end_date = datetime.strptime(request.query_params.get("end_date"), "%Y-%m-%d")
        compare_periods = int(request.query_params.get("compare", 0))
        period_type = request.query_params.get("period_type", "month")

        date_ranges = []
        for i in range(compare_periods + 1):
            if period_type == "month":
                period_start = (start_date - relativedelta(months=i)).replace(day=1)
                period_end = (period_start + relativedelta(months=1)) - timedelta(
                    days=1
                )
            elif period_type == "year":
                period_start = start_date - relativedelta(years=i)
                period_end = end_date - relativedelta(years=i)
            date_ranges.append((period_start, period_end))

        report = {
            "Trading Income": {},
            "Cost of Sales": {},
            "Operating Expenses": {},
            "Equity Movements": {},
            "Other Items": {},
            "totals": {
                key: []
                for key in [
                    "Trading Income",
                    "Cost of Sales",
                    "Gross Profit",
                    "Operating Expenses",
                    "Equity Movements",
                    "Net Profit",
                    "Accounting Profit",
                ]
            },
        }

        for period_index, (period_start, period_end) in enumerate(date_ranges):
            consolidated_rollup = self.rollup_line_items(period_start, period_end)

            for (account_type, account_name), total in consolidated_rollup.items():
                self.categorize_transaction(
                    account_name,
                    account_type,
                    total,
                    report,
                    compare_periods,
                    period_index,
                )

            totals = self.calculate_totals(report, compare_periods, period_index)
            for key, value in totals.items():
                report["totals"][key].append(value)

        return Response(report)
