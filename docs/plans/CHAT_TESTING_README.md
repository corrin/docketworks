# Chat Function Testing Suite

Comprehensive testing framework for the chat functionality in the DocketWorks system.

## Overview

This testing suite provides comprehensive coverage for all chat-related functionality, including:

- **GeminiChatService** - AI-powered chat responses with tool integration
- **Chat API Endpoints** - REST API for chat history and interactions
- **JobQuoteChat Model** - Database model for chat message storage
- **MCP Tool Integration** - Model Context Protocol tools for quoting
- **Performance Testing** - Load testing and optimization validation

## Test Structure

### 1. Unit Tests

#### `test_gemini_chat_service.py`

- Service configuration and initialization
- AI response generation
- Tool integration and execution
- Error handling and edge cases
- Message persistence and metadata

#### `test_job_quote_chat_model.py`

- Model field validation
- Database constraints and relationships
- Serialization and deserialization
- Query optimization
- Large content handling

#### `test_mcp_tool_integration.py`

- QuotingTool functionality
- SupplierProductQueryTool functionality
- Tool parameter validation
- Error handling in tool execution
- Integration with chat service

### 2. Integration Tests

#### `test_chat_api_endpoints.py`

- Complete API flow testing
- Authentication and authorization
- Request/response validation
- Error handling and edge cases
- CORS and OPTIONS handling

### 3. Performance Tests

#### `test_chat_performance.py`

- Response time under different loads
- Memory usage during conversation
- Concurrent chat sessions
- Large conversation history handling
- Database query optimization

### 4. Test Data

#### `fixtures/chat_test_data.json`

- Comprehensive test data fixtures
- Multiple jobs with chat history
- Various AI provider configurations
- Realistic conversation scenarios

## Running Tests

### Basic Test Execution

```bash
# Run all chat tests
python run_chat_tests.py

# Run with coverage reporting
python run_chat_tests.py --coverage

# Run specific test categories
python run_chat_tests.py --unit
python run_chat_tests.py --integration
python run_chat_tests.py --performance
```

### Django Test Runner

```bash
# Run all chat tests
python manage.py test apps.job.tests.test_gemini_chat_service
python manage.py test apps.job.tests.test_chat_api_endpoints
python manage.py test apps.job.tests.test_job_quote_chat_model
python manage.py test apps.job.tests.test_mcp_tool_integration
python manage.py test apps.job.tests.test_chat_performance

# Run with verbosity
python manage.py test apps.job.tests --verbosity=2

# Run with coverage (if django-coverage installed)
coverage run --source='apps.job' manage.py test apps.job.tests
coverage report
coverage html
```

### Test Categories

#### Fast Tests (Unit Tests)

```bash
python run_chat_tests.py --unit
```

- **Duration**: ~30 seconds
- **Coverage**: Core functionality
- **Dependencies**: Mock external services

#### Integration Tests

```bash
python run_chat_tests.py --integration
```

- **Duration**: ~60 seconds
- **Coverage**: API endpoints and workflows
- **Dependencies**: Database, full Django stack

#### Performance Tests

```bash
python run_chat_tests.py --performance
```

- **Duration**: ~120 seconds
- **Coverage**: Load testing and optimization
- **Dependencies**: Database, threading

## Test Coverage Goals

| Component          | Target Coverage | Focus Areas                        |
| ------------------ | --------------- | ---------------------------------- |
| GeminiChatService  | 95%             | AI integration, tool execution     |
| Chat API Views     | 90%             | Request handling, validation       |
| JobQuoteChat Model | 85%             | Database operations, relationships |
| MCP Tools          | 80%             | Tool functionality, error handling |
| Performance        | N/A             | Response time, memory usage        |

## Test Data Management

### Using Fixtures

```python
# Load test data in tests
from django.test import TestCase

class ChatTestCase(TestCase):
    fixtures = ['chat_test_data.json']

    def test_with_fixtures(self):
        # Test data is automatically loaded
        pass
```

### Creating Test Data

```python
# Create test data programmatically
def setUp(self):
    self.job = Job.objects.create(
        name="Test Job",
        job_number="TEST001",
        # ... other fields
    )

    self.chat_message = JobQuoteChat.objects.create(
        job=self.job,
        message_id="test-msg-1",
        role="user",
        content="Test message",
    )
```

## Mocking External Services

### AI Provider Mocking

```python
@patch('apps.job.services.gemini_chat_service.GeminiChatService.get_gemini_client')
def test_ai_response(self, mock_client):
    mock_model = Mock()
    mock_model.model_name = "gemini-pro"
    mock_client.return_value = mock_model

    # Test AI response generation
    result = self.service.generate_ai_response(job_id, "Test message")
    self.assertIsNotNone(result)
```

### Tool Execution Mocking

```python
@patch('apps.job.services.gemini_chat_service.GeminiChatService._execute_mcp_tool')
def test_tool_execution(self, mock_tool):
    mock_tool.return_value = "Tool result"

    # Test tool integration
    result = self.service.generate_ai_response(job_id, "Search products")
    self.assertIn("tool_calls", result.metadata)
```

## Performance Benchmarks

### Response Time Targets

| Operation             | Target Time | Acceptable Range |
| --------------------- | ----------- | ---------------- |
| Basic chat response   | <2 seconds  | <5 seconds       |
| Response with history | <3 seconds  | <8 seconds       |
| Tool execution        | <3 seconds  | <10 seconds      |
| Database queries      | <100ms      | <500ms           |

### Memory Usage Targets

| Scenario            | Target Memory | Maximum |
| ------------------- | ------------- | ------- |
| Single conversation | <50MB         | <100MB  |
| Concurrent sessions | <200MB        | <500MB  |
| Large history       | <100MB        | <250MB  |

### Concurrency Targets

| Metric               | Target | Maximum |
| -------------------- | ------ | ------- |
| Concurrent users     | 10+    | 50+     |
| Messages per second  | 5+     | 20+     |
| Database connections | <10    | <25     |

## Debugging Tests

### Test Failures

```bash
# Run with verbose output
python manage.py test apps.job.tests --verbosity=2

# Run single test method
python manage.py test apps.job.tests.test_gemini_chat_service.GeminiChatServiceTests.test_basic_functionality

# Run with pdb debugging
python manage.py test apps.job.tests --debug-mode
```

### Database Issues

```bash
# Reset test database
python manage.py flush --settings=settings.test

# Run with fresh database
python manage.py test apps.job.tests --keepdb=False
```

### Performance Profiling

```python
# Add profiling to tests
import cProfile
import pstats

def test_with_profiling(self):
    profiler = cProfile.Profile()
    profiler.enable()

    # Run test code
    result = self.service.generate_ai_response(job_id, "Test")

    profiler.disable()
    stats = pstats.Stats(profiler)
    stats.sort_stats('cumulative')
    stats.print_stats(10)
```

## Continuous Integration

### GitHub Actions Integration

```yaml
name: Chat Function Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest

    steps:
      - uses: actions/checkout@v2

      - name: Set up Python
        uses: actions/setup-python@v2
        with:
          python-version: 3.12

      - name: Install dependencies
        run: |
          pip install -r requirements.txt
          pip install coverage

      - name: Run chat tests
        run: |
          python run_chat_tests.py --coverage

      - name: Upload coverage
        uses: codecov/codecov-action@v1
```

### Pre-commit Hooks

```bash
# Install pre-commit hooks
pip install pre-commit
pre-commit install

# Run chat tests before commit
pre-commit run --all-files
```

## Test Maintenance

### Adding New Tests

1. **Choose appropriate test file** based on functionality
2. **Follow naming conventions** (`test_*` methods)
3. **Use appropriate test base class** (TestCase vs TransactionTestCase)
4. **Add proper setup/teardown** methods
5. **Include docstrings** explaining test purpose
6. **Add to test runner** if needed

### Updating Test Data

1. **Update fixtures** when models change
2. **Maintain backward compatibility** where possible
3. **Document breaking changes** in test data
4. **Version test data** if needed

### Performance Test Maintenance

1. **Update benchmarks** as system improves
2. **Add new performance tests** for new features
3. **Monitor test execution time** and optimize slow tests
4. **Update hardware-specific targets** as needed

## Troubleshooting

### Common Issues

1. **Database connection errors**

   - Check database settings
   - Ensure test database exists
   - Verify permissions

2. **Import errors**

   - Check PYTHONPATH
   - Verify Django settings
   - Check for circular imports

3. **Mock failures**

   - Verify mock paths
   - Check mock configuration
   - Ensure patches are applied correctly

4. **Performance test failures**
   - Check system resources
   - Verify test environment
   - Adjust timing expectations

### Getting Help

- Review test output for specific error messages
- Check Django test documentation
- Review existing test patterns in codebase
- Consult team members for complex issues

## Future Enhancements

### Planned Improvements

1. **End-to-end testing** with real browser automation
2. **Load testing** with realistic user scenarios
3. **Security testing** for chat functionality
4. **Accessibility testing** for chat interfaces
5. **Mobile testing** for responsive chat features

### Test Infrastructure

1. **Parallel test execution** for faster feedback
2. **Test result reporting** and analytics
3. **Automated test data generation**
4. **Visual regression testing** for UI components
5. **API contract testing** for external integrations
