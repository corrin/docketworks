# Fix: seed_xero_from_database

Add progress logging before/after the bulk Xero fetch calls. Use `page_size=1000` to reduce pagination. Two lines of logging, one parameter change.
