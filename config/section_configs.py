SECTION_CONFIGS = {
    '1-2F': {'section_id': 4, 'check_oncall_next': True},
    '3F': {'section_id': 5, 'check_oncall_next': True},
    '4F': {'section_id': 6, 'check_oncall_next': True},
    '4F_月': {'section_id': 6, 'check_oncall_next': True},
    '4F_火': {'section_id': 6, 'check_oncall_next': True},
    '5F': {'section_id': 7, 'check_oncall_next': True},
    '化療': {'section_id': 9, 'check_oncall_next': True},
    'DI': {'section_id': 8, 'check_oncall_next': True},
    '調剤室_月木_非祝日': {'section_id': 1, 'check_oncall_next': True},
    '調剤室_火_非祝日': {'section_id': 1, 'check_oncall_next': True},
    '調剤室_金_非祝日': {'section_id': 1, 'check_oncall_next': True},
    '調剤室_土': {'section_id': 1, 'check_oncall_next': True},
    '調剤室_日祝': {'section_id': 1, 'check_oncall_next': True},
    '入退院センター': {'section_id': 3, 'check_oncall_next': True},
    '感染管理': {'section_id': 14, 'check_oncall_next': True},
    'ポリファーマシー': {'section_id': 11, 'check_oncall_next': True},
    '心不全回診': {'section_id': 18, 'check_oncall_next': False},
    'NST': {'section_id': 19, 'check_oncall_next': False},
    '実習': {'section_id': 20, 'check_oncall_next': False},
    'マスター管理': {'section_id': 21, 'check_oncall_next': False},
    'RI': {'section_id': 22, 'check_oncall_next': False},
    '課長業務': {'section_id': 23, 'check_oncall_next': False},
    '医薬品安全使用WG': {'section_id': 24, 'check_oncall_next': False},
    'せん妄ラウンド': {'section_id': 12, 'check_oncall_next': False},
    '課長': {'section_id': 25, 'check_oncall_next': True},
    '部長': {'section_id': 26, 'check_oncall_next': False},
}


def make_section_configs(assigned_lists, required_staff_12, required_list):
    """セクション設定を作成する
    Args:
        assigned_lists (_type_): 各セクションに割り当てられたスタッフのリスト
        required_staff_12 (_type_): 1-2Fの必須スタッフ
        required_list (_type_): 1-2Fの必須スタッフリスト

    Returns:
        dict: セクションごとの設定を含む辞書
    """
    section_configs = {
        section_name: {
            **config,
            'assigned_list': assigned_lists[section_name],
            'available_list': [],
            'check_day_off': True,
        }
        for section_name, config in SECTION_CONFIGS.items()
    }
    #1-2Fの必須スタッフ
    section_configs['1-2F']['required_staff'] = required_staff_12
    section_configs['1-2F']['required_list'] = required_list
    return section_configs