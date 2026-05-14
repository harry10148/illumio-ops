import pandas as pd
import pytest
from src.report.analysis.mod10_allowed_traffic import allowed_traffic

@pytest.fixture
def sample_df():
    return pd.DataFrame({
        'policy_decision': ['allowed'] * 5,
        'src_app': ['app_a'] * 5,
        'dst_app': ['app_b'] * 5,
        'port': [80, 443, 53, 80, 443],
        'num_connections': [100, 200, 50, 150, 250],
        'src_managed': [True] * 5,
    })

def test_chart_type_is_bar(sample_df):
    result = allowed_traffic(sample_df, top_n=10)
    assert result['chart_spec']['type'] == 'bar'

def test_chart_data_uses_labels_values_keys(sample_df):
    result = allowed_traffic(sample_df, top_n=10)
    data = result['chart_spec']['data']
    assert 'labels' in data
    assert 'values' in data
    assert 'x' not in data
    assert 'y' not in data

def test_chart_title_key_is_top_allowed_ports(sample_df):
    result = allowed_traffic(sample_df, top_n=10)
    assert result['chart_spec']['title_key'] == 'rpt_chart_top_allowed_ports'

def test_chart_data_sorted_by_connections_descending(sample_df):
    result = allowed_traffic(sample_df, top_n=10)
    data = result['chart_spec']['data']
    # sample_df has: port 80→250 connections, 443→450 connections, 53→50 connections
    # Expected order: 443 (450), 80 (250), 53 (50)
    assert data['labels'][0] == '443'
    assert data['labels'][1] == '80'
    assert data['labels'][2] == '53'
    assert data['values'][0] >= data['values'][1] >= data['values'][2]
