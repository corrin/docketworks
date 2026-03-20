# Accounts URLs Documentation

<!-- This file is auto-generated. To regenerate, run: python scripts/generate_url_docs.py -->

### Authentication
| URL Pattern | View | Name | Description |
|-------------|------|------|-------------|
| `/logout/` | `user_profile_view.LogoutUserAPIView` | `accounts:api_logout` | Custom logout view that clears JWT httpOnly cookies |

### Me Management
| URL Pattern | View | Name | Description |
|-------------|------|------|-------------|
| `/me/` | `user_profile_view.GetCurrentUserAPIView` | `accounts:get_current_user` | Get current authenticated user information via JWT from httpOnly cookie |

### Password_Change Management
| URL Pattern | View | Name | Description |
|-------------|------|------|-------------|
| `/password_change/` | `password_views.SecurityPasswordChangeView` | `accounts:password_change` | Custom password change view with enhanced security requirements. |

### Staff Management
| URL Pattern | View | Name | Description |
|-------------|------|------|-------------|
| `/staff/` | `staff_api.StaffListCreateAPIView` | `accounts:api_staff_list_create` | API endpoint for listing and creating staff members. |
| `/staff/<uuid:pk>/` | `staff_api.StaffRetrieveUpdateDestroyAPIView` | `accounts:api_staff_detail` | API endpoint for retrieving, updating, and deleting individual staff members. |
| `/staff/all/` | `staff_views.StaffListAPIView` | `accounts:api_staff_all_list` | API endpoint for retrieving list of staff members for Kanban board. |
| `/staff/rates/<uuid:staff_id>/` | `staff_views.get_staff_rates` | `accounts:get_staff_rates` | Retrieve wage rates for a specific staff member. |

### Token Management
| URL Pattern | View | Name | Description |
|-------------|------|------|-------------|
| `/token/` | `token_view.CustomTokenObtainPairView` | `accounts:token_obtain_pair` | Customized token obtain view that handles password reset requirement |
| `/token/refresh/` | `token_view.CustomTokenRefreshView` | `accounts:token_refresh` | Customized token refresh view that uses httpOnly cookies |
