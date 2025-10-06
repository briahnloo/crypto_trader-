#!/usr/bin/env python3
"""
Comprehensive test runner for all critical functionality.
Runs all test suites and provides detailed reporting.
"""

import unittest
import sys
import os
import time
from datetime import datetime

# Add the src directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

# Import all test modules
from test_risk_management import TestRiskManagement, TestRiskManagementIntegration
from test_api_error_handling import TestAPIErrorHandling, TestAPIErrorHandlingIntegration
from test_equity_calculations import TestEquityCalculations, TestEquityCalculationsIntegration
from test_paper_trading import TestPaperTrading, TestPaperTradingIntegration


class ComprehensiveTestRunner:
    """Comprehensive test runner for all critical functionality."""
    
    def __init__(self):
        """Initialize the test runner."""
        self.test_suites = []
        self.results = {}
        self.start_time = None
        self.end_time = None
    
    def add_test_suite(self, test_class, suite_name):
        """Add a test suite to the runner."""
        suite = unittest.makeSuite(test_class)
        self.test_suites.append((suite, suite_name))
    
    def run_all_tests(self):
        """Run all test suites and collect results."""
        print("🚀 Starting Comprehensive Test Suite")
        print("=" * 60)
        print(f"Test execution started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print()
        
        self.start_time = time.time()
        
        # Add all test suites
        self.add_test_suite(TestRiskManagement, "Risk Management Unit Tests")
        self.add_test_suite(TestRiskManagementIntegration, "Risk Management Integration Tests")
        self.add_test_suite(TestAPIErrorHandling, "API Error Handling Unit Tests")
        self.add_test_suite(TestAPIErrorHandlingIntegration, "API Error Handling Integration Tests")
        self.add_test_suite(TestEquityCalculations, "Equity Calculations Unit Tests")
        self.add_test_suite(TestEquityCalculationsIntegration, "Equity Calculations Integration Tests")
        self.add_test_suite(TestPaperTrading, "Paper Trading Unit Tests")
        self.add_test_suite(TestPaperTradingIntegration, "Paper Trading Integration Tests")
        
        # Run each test suite
        for suite, suite_name in self.test_suites:
            print(f"🧪 Running {suite_name}...")
            runner = unittest.TextTestRunner(verbosity=1, stream=open(os.devnull, 'w'))
            result = runner.run(suite)
            
            self.results[suite_name] = {
                'tests_run': result.testsRun,
                'failures': len(result.failures),
                'errors': len(result.errors),
                'success_rate': ((result.testsRun - len(result.failures) - len(result.errors)) / result.testsRun * 100) if result.testsRun > 0 else 0,
                'failures_list': result.failures,
                'errors_list': result.errors
            }
            
            # Print suite result
            if result.failures or result.errors:
                print(f"   ❌ {suite_name}: {result.testsRun - len(result.failures) - len(result.errors)}/{result.testsRun} passed")
            else:
                print(f"   ✅ {suite_name}: {result.testsRun}/{result.testsRun} passed")
        
        self.end_time = time.time()
        
        # Print comprehensive summary
        self.print_comprehensive_summary()
    
    def print_comprehensive_summary(self):
        """Print comprehensive test summary."""
        print("\n" + "=" * 60)
        print("📊 COMPREHENSIVE TEST SUMMARY")
        print("=" * 60)
        
        # Calculate totals
        total_tests = sum(result['tests_run'] for result in self.results.values())
        total_failures = sum(result['failures'] for result in self.results.values())
        total_errors = sum(result['errors'] for result in self.results.values())
        total_passed = total_tests - total_failures - total_errors
        overall_success_rate = (total_passed / total_tests * 100) if total_tests > 0 else 0
        
        # Print overall statistics
        print(f"Total Tests Run: {total_tests}")
        print(f"Total Passed: {total_passed}")
        print(f"Total Failures: {total_failures}")
        print(f"Total Errors: {total_errors}")
        print(f"Overall Success Rate: {overall_success_rate:.1f}%")
        print(f"Execution Time: {self.end_time - self.start_time:.2f} seconds")
        
        # Print detailed results by suite
        print("\n📋 DETAILED RESULTS BY TEST SUITE:")
        print("-" * 60)
        
        for suite_name, result in self.results.items():
            status = "✅ PASS" if result['failures'] == 0 and result['errors'] == 0 else "❌ FAIL"
            print(f"{status} {suite_name}")
            print(f"   Tests: {result['tests_run']}, Passed: {result['tests_run'] - result['failures'] - result['errors']}, "
                  f"Failed: {result['failures']}, Errors: {result['errors']}, Success Rate: {result['success_rate']:.1f}%")
        
        # Print failures and errors
        if total_failures > 0 or total_errors > 0:
            print("\n🚨 FAILURES AND ERRORS:")
            print("-" * 60)
            
            for suite_name, result in self.results.items():
                if result['failures'] or result['errors']:
                    print(f"\n{suite_name}:")
                    
                    if result['failures']:
                        print("  Failures:")
                        for test, traceback in result['failures_list']:
                            print(f"    - {test}")
                    
                    if result['errors']:
                        print("  Errors:")
                        for test, traceback in result['errors_list']:
                            print(f"    - {test}")
        
        # Print recommendations
        print("\n💡 RECOMMENDATIONS:")
        print("-" * 60)
        
        if overall_success_rate >= 95:
            print("✅ EXCELLENT: System is ready for live trading with high confidence")
            print("   - All critical functionality is working correctly")
            print("   - Risk management is properly implemented")
            print("   - API error handling is robust")
            print("   - Equity calculations are accurate")
            print("   - Paper trading is functioning correctly")
        elif overall_success_rate >= 90:
            print("⚠️  GOOD: System is mostly ready but needs attention to failed tests")
            print("   - Review and fix any failed tests before live trading")
            print("   - Ensure all critical functionality is working")
            print("   - Consider additional testing for edge cases")
        elif overall_success_rate >= 80:
            print("⚠️  FAIR: System needs significant improvements before live trading")
            print("   - Fix all failed tests before proceeding")
            print("   - Review risk management implementation")
            print("   - Test all critical functionality thoroughly")
        else:
            print("❌ POOR: System is not ready for live trading")
            print("   - Fix all critical issues before proceeding")
            print("   - Review system architecture and implementation")
            print("   - Consider additional development and testing")
        
        # Print next steps
        print("\n🎯 NEXT STEPS:")
        print("-" * 60)
        
        if total_failures == 0 and total_errors == 0:
            print("1. ✅ All tests passed - system is ready for live trading")
            print("2. 🔄 Run paper trading for at least 7 days")
            print("3. 📊 Monitor performance metrics")
            print("4. 🛡️  Verify all safety mechanisms are working")
            print("5. 🚀 Consider live trading with small position sizes")
        else:
            print("1. 🔧 Fix all failed tests and errors")
            print("2. 🧪 Re-run the test suite to verify fixes")
            print("3. 📋 Review system documentation and requirements")
            print("4. 🔍 Perform additional manual testing")
            print("5. ⚠️  Do not proceed to live trading until all tests pass")
        
        print("\n" + "=" * 60)
        print("Test execution completed successfully!")
        print("=" * 60)


def main():
    """Main function to run comprehensive tests."""
    try:
        runner = ComprehensiveTestRunner()
        runner.run_all_tests()
        
        # Exit with appropriate code
        total_failures = sum(result['failures'] for result in runner.results.values())
        total_errors = sum(result['errors'] for result in runner.results.values())
        
        if total_failures == 0 and total_errors == 0:
            sys.exit(0)  # Success
        else:
            sys.exit(1)  # Failure
            
    except Exception as e:
        print(f"❌ Test runner failed with error: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
