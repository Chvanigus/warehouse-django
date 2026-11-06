"""Стандартные роли веб-интерфейса и их складские полномочия."""

WAREHOUSE_ROLES = {
    'operator': 'Склад · оператор',
    'reviewer': 'Склад · контролёр',
    'admin': 'Склад · администратор',
}
WAREHOUSE_ROLE_LABELS = {
    'operator': 'Оператор',
    'reviewer': 'Проверяющий',
    'admin': 'Администратор',
}

CATALOG_MODELS = {
    'company', 'contractors', 'machineworker', 'machines', 'measuremeasurement',
    'spares', 'trailers', 'warehouses', 'workers',
}
READ_PERMISSIONS = {
    f'view_{model}' for model in CATALOG_MODELS | {
        'receipt', 'writeoff', 'stocktransfer', 'movement', 'stock',
        'inventorycount', 'inventorysheet', 'stockminimum', 'stockadjustment', 'stockrequest',
    }
}
OPERATOR_PERMISSIONS = READ_PERMISSIONS | {
    'add_receipt', 'add_writeoff', 'add_stocktransfer', 'add_inventorycount', 'add_inventorysheet',
    'add_stockrequest',
}
REVIEWER_PERMISSIONS = OPERATOR_PERMISSIONS | {
    'approve_stockrequest', 'approve_inventorysheet',
    'delete_receipt', 'delete_writeoff', 'delete_stocktransfer', 'add_stock', 'change_stock',
    'add_stockminimum', 'change_stockminimum', 'delete_stockminimum',
} | {
    f'{action}_{model}' for action in ('add', 'change') for model in CATALOG_MODELS
}
WAREHOUSE_ROLE_PERMISSIONS = {
    'operator': OPERATOR_PERMISSIONS,
    'reviewer': REVIEWER_PERMISSIONS,
    'admin': REVIEWER_PERMISSIONS | {'manage_warehouse_users'},
}
