#!/usr/bin/env python3
"""
Convert Django JSON backup to MySQL dump format.
Takes the anonymized JSON backup and produces SQL INSERT statements.
"""

import json
import logging
import os
import sys
from datetime import datetime
from typing import Any, Dict, List

from dateutil import parser


class JSONToMySQLConverter:
    def __init__(self):
        # DateTime fields that need conversion (from INFORMATION_SCHEMA)
        self.datetime_fields = {
            "action_time",
            "applied",
            "completed_at",
            "created",
            "created_at",
            "created_date_utc",
            "date",
            "date_joined",
            "django_created_at",
            "django_updated_at",
            "expires_at",
            "expire_date",
            "history_date",
            "last_login",
            "last_scraped",
            "last_xero_deep_sync",
            "last_xero_sync",
            "next_run_time",
            "quote_acceptance_date",
            "run_time",
            "started_at",
            "timestamp",
            "updated_at",
            "uploaded_at",
            "xero_last_modified",
            "xero_last_synced",
            "delivery_date",
            "expected_delivery",
            "order_date",
            "parsed_at",
        }

        # JSON fields that need proper JSON formatting
        self.json_fields = {
            "raw_json",
            "additional_contact_persons",
            "all_phones",
            "ext_refs",
            "meta",
            "metadata",
            "summary",
            "raw_line_data",
            "delta_before",
            "delta_after",
            "delta_meta",
            "form_schema",
        }

        # Mapping from Django model names to MySQL table names
        self.model_to_table = {
            "job.job": "workflow_job",
            "job.jobpricing": "workflow_jobpricing",
            "job.jobpart": "workflow_jobpart",
            "job.materialentry": "workflow_materialentry",
            "job.adjustmententry": "workflow_adjustmententry",
            "job.jobevent": "workflow_jobevent",
            "job.jobfile": "workflow_jobfile",
            "job.jobquotechat": "job_quote_chat",
            # New pricing model tables
            "job.costset": "job_costset",
            "job.costline": "job_costline",
            "timesheet.timeentry": "workflow_timeentry",
            "accounts.staff": "workflow_staff",
            "client.client": "workflow_client",
            "client.clientcontact": "client_contact",
            "client.supplierpickupaddress": "client_supplier_pickup_address",
            "quoting.supplierpricelist": "quoting_supplierpricelist",
            "quoting.supplierproduct": "quoting_supplierproduct",
            "quoting.scrapejob": "quoting_scrapejob",
            "purchasing.purchaseorder": "workflow_purchaseorder",
            "purchasing.purchaseorderline": "workflow_purchaseorderline",
            "purchasing.stock": "workflow_stock",
            "process.form": "process_form",
            "process.formentry": "process_form_entry",
            "process.procedure": "process_procedure",
            "contenttypes.contenttype": "django_content_type",
            "migrations.migration": "django_migrations",
        }

        # Field mappings for ForeignKey fields (Django field -> MySQL column)
        self.field_mappings = {
            "workflow_client": {
                "merged_into": "merged_into_id",
            },
            "workflow_job": {
                "client": "client_id",
                "created_by": "created_by_id",
                "contact": "contact_id",
                "latest_estimate_pricing": "latest_estimate_pricing_id",
                "latest_quote_pricing": "latest_quote_pricing_id",
                "latest_reality_pricing": "latest_reality_pricing_id",
                # New pricing model - map field names to match schema
                "latest_estimate": "latest_estimate_id",
                "latest_quote": "latest_quote_id",
                "latest_actual": "latest_actual_id",
                "default_xero_pay_item": "default_xero_pay_item_id",
            },
            "workflow_jobpricing": {
                "job": "job_id",
                "default_part": "default_part_id",
            },
            "workflow_jobpart": {
                "job_pricing": "job_pricing_id",
            },
            "workflow_materialentry": {
                "job_part": "job_part_id",
                "job_pricing": "job_pricing_id",
                "purchase_order_line": "purchase_order_line_id",
                "source_stock": "source_stock_id",
            },
            "workflow_adjustmententry": {
                "job_part": "job_part_id",
                "job_pricing": "job_pricing_id",
            },
            "workflow_jobevent": {
                "job": "job_id",
                "staff": "staff_id",
            },
            "workflow_jobfile": {
                "job": "job_id",
            },
            "job_quote_chat": {
                "job": "job_id",
            },
            "workflow_timeentry": {
                "staff": "staff_id",
                "job_pricing": "job_pricing_id",
            },
            "client_contact": {
                "client": "client_id",
            },
            "client_supplier_pickup_address": {
                "client": "client_id",
            },
            "quoting_supplierproduct": {
                "price_list": "price_list_id",
                "supplier": "supplier_id",
            },
            "quoting_supplierpricelist": {
                "supplier": "supplier_id",
            },
            "quoting_scrapejob": {
                "supplier": "supplier_id",
            },
            # New pricing model field mappings
            "job_costset": {
                "job": "job_id",
            },
            "job_costline": {
                "cost_set": "cost_set_id",
                "xero_pay_item": "xero_pay_item_id",
            },
            "workflow_purchaseorder": {
                "supplier": "supplier_id",
                "job": "job_id",
                "created_by": "created_by_id",
                "pickup_address": "pickup_address_id",
            },
            "workflow_purchaseorderline": {
                "purchase_order": "purchase_order_id",
                "job": "job_id",
            },
            "workflow_stock": {
                "job": "job_id",
                "source_parent_stock": "source_parent_stock_id",
                "source_purchase_order_line": "source_purchase_order_line_id",
            },
            "process_form_entry": {
                "form": "form_id",
                "job": "job_id",
                "staff": "staff_id",
                "entered_by": "entered_by_id",
            },
            "process_procedure": {
                "job": "job_id",
            },
        }

        # Many-to-many field mappings
        self.m2m_mappings = {
            "workflow_job": {
                "archived_pricings": "workflow_job_archived_pricings",
                "people": "workflow_job_people",
            },
            "workflow_staff": {
                "groups": "workflow_staff_groups",
                "user_permissions": "workflow_staff_user_permissions",
            },
        }

    def escape_sql_value(self, value: Any, field_name: str = None) -> str:
        """Escape value for SQL insertion."""
        if value is None:
            return "NULL"
        elif isinstance(value, bool):
            return "1" if value else "0"
        elif isinstance(value, (int, float)):
            return str(value)
        elif isinstance(value, str):
            # Convert datetime fields using proper parsing
            if field_name in self.datetime_fields and ("T" in value or "Z" in value):
                try:
                    # Parse ISO datetime and format for MySQL
                    dt = parser.parse(value)
                    mysql_datetime = dt.strftime("%Y-%m-%d %H:%M:%S")
                    return f"'{mysql_datetime}'"
                except (ValueError, TypeError):
                    # If parsing fails, treat as regular string
                    logging.warning(
                        f"Failed to parse datetime '{value}' for field '{field_name}'"
                    )

            # Escape single quotes, backslashes, and newlines
            escaped = (
                value.replace("\\", "\\\\")
                .replace("'", "\\'")
                .replace("\n", "\\n")
                .replace("\r", "\\r")
            )
            return f"'{escaped}'"
        elif isinstance(value, (dict, list)):
            # Handle JSON fields (dict/list objects should remain as proper JSON)
            if field_name in self.json_fields:
                import json

                json_str = json.dumps(value)
                escaped = json_str.replace("\\", "\\\\").replace("'", "\\'")
                return f"'{escaped}'"
            else:
                # For non-JSON fields, this shouldn't happen for regular fields,
                # only M2M
                logging.warning(
                    f"Unexpected dict/list value for non-JSON field '{field_name}': "
                    f"{type(value)} - {str(value)[:100]}..."
                )
                return "NULL"
        elif isinstance(value, list):
            # This shouldn't happen for regular fields, only M2M
            return "NULL"
        else:
            # Convert to string and escape
            escaped = str(value).replace("\\", "\\\\").replace("'", "\\'")
            return f"'{escaped}'"

    def convert_record(self, record: Dict) -> List[str]:
        """Convert a single Django JSON record to SQL INSERT statements."""
        model = record["model"]
        pk = record["pk"]
        fields = record["fields"]

        if model not in self.model_to_table:
            print(f"Warning: Unknown model {model}, skipping", file=sys.stderr)
            return []

        table_name = self.model_to_table[model]
        statements = []

        # Build field list and values for main table
        columns = ["id"]  # Primary key first
        values = [self.escape_sql_value(pk)]

        # Process regular fields
        field_mapping = self.field_mappings.get(table_name, {})
        m2m_fields = {}

        for field_name, field_value in fields.items():
            # Skip many-to-many fields for now
            if (
                table_name in self.m2m_mappings
                and field_name in self.m2m_mappings[table_name]
            ):
                m2m_fields[field_name] = field_value
                continue

            # Map field name if needed
            column_name = field_mapping.get(field_name, field_name)
            columns.append(column_name)
            values.append(self.escape_sql_value(field_value, field_name))

        # Generate main INSERT statement
        columns_str = ", ".join(f"`{col}`" for col in columns)
        values_str = ", ".join(values)
        main_insert = (
            f"INSERT INTO `{table_name}` ({columns_str}) VALUES ({values_str});"
        )
        statements.append(main_insert)

        # Generate M2M INSERT statements
        if table_name in self.m2m_mappings:
            for field_name, related_ids in m2m_fields.items():
                if not related_ids:  # Skip empty lists
                    continue

                m2m_table = self.m2m_mappings[table_name][field_name]

                for related_id in related_ids:
                    if field_name == "archived_pricings":
                        m2m_insert = (
                            f"INSERT INTO `{m2m_table}` "
                            f"(`job_id`, `jobpricing_id`) VALUES "
                            f"({self.escape_sql_value(pk)}, "
                            f"{self.escape_sql_value(related_id)});"
                        )
                    elif field_name == "people":
                        m2m_insert = (
                            f"INSERT INTO `{m2m_table}` "
                            f"(`job_id`, `staff_id`) VALUES "
                            f"({self.escape_sql_value(pk)}, "
                            f"{self.escape_sql_value(related_id)});"
                        )
                    else:
                        print(
                            f"Warning: Unknown M2M field {field_name}", file=sys.stderr
                        )
                        continue

                    statements.append(m2m_insert)

        return statements

    def convert_file(self, input_file: str, output_file: str):
        """Convert entire JSON file to SQL dump."""
        print(f"Converting {input_file} to {output_file}")

        with open(input_file, "r") as f:
            data = json.load(f)

        with open(output_file, "w") as f:
            # Write header
            f.write("-- MySQL dump converted from Django JSON backup\n")
            f.write(f"-- Generated on {datetime.now()}\n")
            f.write("-- \n\n")
            db_name = os.getenv("MYSQL_DATABASE", "dw_msm_dev")
            f.write(f"USE {db_name};\n")
            f.write("SET FOREIGN_KEY_CHECKS=0;\n\n")

            # Process each record
            total_records = len(data)
            for i, record in enumerate(data):
                if i % 1000 == 0:
                    print(f"Processing record {i}/{total_records}")

                statements = self.convert_record(record)
                for statement in statements:
                    f.write(statement + "\n")

            f.write("\nSET FOREIGN_KEY_CHECKS=1;\n")
            f.write("-- Conversion completed\n")

        print(f"Conversion completed: {output_file}")


def main():
    if len(sys.argv) != 2:
        print("Usage: python json_to_mysql.py <input.json>")
        sys.exit(1)

    input_file = sys.argv[1]
    # Generate output filename from input filename
    output_file = input_file.replace(".json", ".sql")

    converter = JSONToMySQLConverter()
    converter.convert_file(input_file, output_file)


if __name__ == "__main__":
    main()
