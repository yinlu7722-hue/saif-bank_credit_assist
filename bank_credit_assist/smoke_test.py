"""
smoke_test.py — 全流程冒烟测试（纯本地计算，不消耗 API）
"""
import asyncio
import sys

def main():
    print('=' * 60)
    print('SMOKE TEST: 全模块导入 + 数据模型 + 纯计算')
    print('=' * 60)

    # ── 1. 全模块导入验证 ──────────────────────────
    print('\n[1/7] 模块导入...')
    from shared.config import PROJECT_ROOT, OUTPUT_DIR, API_ACCESS_KEY
    from shared.data_schema import (
        DataSource, CompanyBasicInfo, FinancialAnalysis, FinalReport,
        UNIFIED_DOCUMENT_LIST, UNIFIED_REQUIRED_CODES,
        UNIFIED_EXCEL_EXTENSIONS, UNIFIED_TEXT_EXTENSIONS, DocumentLevel
    )
    from shared.parsing import parse_number
    from shared.encoding import fix_windows_console_encoding
    from shared.llm_client import create_anthropic_client
    from shared.utils import safe_print, strip_markdown_fences
    from phase2_calculator import compute_financial_ratios, merge_extracted_and_computed, compute_annual_indicators_per_year
    from phase2_compliance import ComplianceScreener
    from phase1_parser import EXCEL_EXTENSIONS, MINERU_EXTENSIONS
    from server import SessionState, SESSION_TTL_SECONDS, _sanitize_filename, _safe_error
    print('  [OK] All 16 modules imported')

    # ── 2. 统一文档清单验证 ─────────────────────────
    print('\n[2/7] 文档清单统一性...')
    codes = [d['code'] for d in UNIFIED_DOCUMENT_LIST]
    levels = [d['level'] for d in UNIFIED_DOCUMENT_LIST]
    assert len(UNIFIED_DOCUMENT_LIST) == 20, f'Expected 20 docs, got {len(UNIFIED_DOCUMENT_LIST)}'
    assert UNIFIED_REQUIRED_CODES == {'A1', 'A2', 'B1', 'B2'}, f'Required mismatch: {UNIFIED_REQUIRED_CODES}'
    assert len([l for l in levels if l == 'required']) == 4
    print(f'  [OK] {len(UNIFIED_DOCUMENT_LIST)} docs, required={UNIFIED_REQUIRED_CODES}')

    # ── 3. parse_number 验证 ─────────────────────────
    print('\n[3/7] parse_number...')
    tests = [
        ('100万', 1000000.0),
        ('1.5亿', 150000000.0),
        ('-3,000', -3000.0),
        ('25.5%', 0.255),
        ('1,234.56', 1234.56),
        (None, None),
        (42, 42.0),
        ('abc', None),
    ]
    for inp, expected in tests:
        result = parse_number(inp)
        assert result == expected, f'parse_number({inp!r}) = {result}, expected {expected}'
    print(f'  [OK] All {len(tests)} test cases passed')

    # ── 4. 财务指标计算（纯数学）─────────────────────
    print('\n[4/7] 财务指标计算...')
    mock_financial = {
        'operating_revenue': 320000000,
        'operating_cost': 240000000,
        'net_profit': 28500000,
        'total_profit': 38000000,
        'current_assets': 165000000,
        'current_liabilities': 95000000,
        'inventory': 42000000,
        'total_assets': 285000000,
        'total_liabilities': 128000000,
        'total_equity': 157000000,
        'accounts_receivable': 75000000,
        'accounts_payable': 52000000,
        'short_term_borrowing': 55000000,
        'notes_payable': 0,
        'long_term_borrowing': 30000000,
        'bonds_payable': 0,
        'cash_equivalents': 25000000,
        'trading_financial_assets': 10000000,
        'notes_receivable': 7000000,
    }
    computed = compute_financial_ratios(mock_financial)
    assert computed.get('gross_margin_calc') == 25.0
    assert computed.get('current_ratio_calc') == round(165/95, 2)
    assert computed.get('quick_ratio') == round((165000000-42000000)/95000000, 2)
    assert computed.get('net_margin') == round(28500000/320000000*100, 2)
    assert computed.get('rigid_liabilities') == 85000000.0
    assert computed.get('cash_assets') == 42000000.0
    assert computed.get('rigid_liability_net') == 43000000.0
    assert 'dupont_analysis' in computed
    dupont = computed['dupont_analysis']
    roe = (dupont['net_margin_pct']/100) * dupont['asset_turnover'] * dupont['equity_multiplier'] * 100
    print(f'  [OK] {len(computed)} indicators. DuPont ROE={round(roe,2)}%')

    # merge
    merged = merge_extracted_and_computed(mock_financial, computed)
    assert merged.get('gross_margin_calc') == 25.0
    print(f'  [OK] merge: {len(merged)} fields')

    # ── 5. 年度指标计算 ──────────────────────────────
    print('\n[5/7] 年度指标计算...')
    annual_data = {
        2023: {'total_assets': 248000000, 'total_liabilities': 115000000, 'operating_revenue': 271000000,
               'operating_cost': 208000000, 'net_profit': 23400000, 'current_assets': 140000000,
               'current_liabilities': 88000000, 'inventory': 38000000, 'accounts_receivable': 65000000,
               'accounts_payable': 48000000, 'total_profit': 31000000, 'short_term_borrowing': 48000000,
               'notes_payable': 0, 'long_term_borrowing': 25000000, 'bonds_payable': 0,
               'cash_equivalents': 20000000, 'trading_financial_assets': 8000000, 'notes_receivable': 5000000},
        2024: {'total_assets': 285000000, 'total_liabilities': 128000000, 'operating_revenue': 320000000,
               'operating_cost': 240000000, 'net_profit': 28500000, 'current_assets': 165000000,
               'current_liabilities': 95000000, 'inventory': 42000000, 'accounts_receivable': 75000000,
               'accounts_payable': 52000000, 'total_profit': 38000000, 'short_term_borrowing': 55000000,
               'notes_payable': 0, 'long_term_borrowing': 30000000, 'bonds_payable': 0,
               'cash_equivalents': 25000000, 'trading_financial_assets': 10000000, 'notes_receivable': 7000000},
    }
    ann = compute_annual_indicators_per_year(annual_data)
    assert len(ann) == 2
    assert ann[2024].get('debt_to_asset_ratio') == round(128/285*100, 2)
    assert ann[2023].get('current_ratio') == round(140/88, 2)
    print(f'  [OK] {len(ann)} years, {len(ann[2024])} indicators/year')

    # ── 6. Pydantic 数据模型 + Session + 安全 ────────
    print('\n[6/7] 数据模型 + Session + 安全...')
    ds = DataSource(source_file='test.pdf', source_location='table_1', confidence_score=0.95)
    cbi = CompanyBasicInfo(company_name='TestCo', unified_social_credit_code='91440300MA5DXXXXX',
                           legal_representative='Zhang San', registered_capital='1000万元',
                           registration_date='2020-01-01', business_scope='Manufacturing', data_source=ds)
    assert cbi.company_name == 'TestCo'
    fr = FinalReport(enterprise_name='TestCo', report_date='2026-05-24', overall_risk_level='中', compliance_status='PASS')
    assert fr.overall_risk_level == '中'

    s = SessionState()
    assert s.workflow_status == 'idle'
    assert hasattr(s, 'created_at')
    assert hasattr(s, 'last_accessed')
    assert SESSION_TTL_SECONDS == 3600

    assert _sanitize_filename('../../../etc/passwd') == 'passwd'
    assert _sanitize_filename('a:b?c*d<e>f|g') == 'b_c_d_e_f_g'
    assert _sanitize_filename('') == 'unnamed_file'

    msg = _safe_error(Exception('secret info'))
    assert 'secret' not in msg
    assert '错误ID' in msg

    assert strip_markdown_fences('```json\n{}\n```') == '{}'
    assert strip_markdown_fences('{}') == '{}'

    fix_windows_console_encoding()
    print('  [OK] All model + security tests passed')

    # ── 7. ComplianceScreener 异步接口 ──────────────
    print('\n[7/7] ComplianceScreener...')
    async def test_async():
        cs = ComplianceScreener()
        result = await cs.run_checks({'enterprise_name': 'test'})
        assert result['overall'] == 'PENDING'
        return result
    asyncio.run(test_async())
    print('  [OK] ComplianceScreener placeholder')

    print('\n' + '=' * 60)
    print('  ALL SMOKE TESTS PASSED — 纯代码路径验证完成')
    print('=' * 60)
    return True

if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)
