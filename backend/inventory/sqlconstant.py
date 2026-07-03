_INVENTORY_KEYWORDS = (
    "库存",
    "库存量",
    "库存查询",
    "查库存",
    "余量",
    "剩余",
    "数量",
    "多少",
    "有货",
    "缺货",
    "库",
)

# Phrases for semantic (embedding) similarity toward inventory-query intent.
_INVENTORY_INTENT_PROTOTYPES = (
    "查一下库存还有多少",
    "查询这个物料的库存情况",
    "仓库里有没有这个配件的现货",
    "库存余量和可用数量是多少",
    "帮忙看看有没有库存",
    "图中物品是否在库存里",
    "识别图片里的东西在不在库存",
    "这个规格有没有货",
)

# Weighted fusion in intent_detection (sum to 1.0).
INTENT_WEIGHT_KEYWORD = 0.25
INTENT_WEIGHT_MODEL = 0.45
INTENT_WEIGHT_EMBEDDING = 0.30
INTENT_INVENTORY_SCORE_THRESHOLD = 0.45

SKU_MASTER = [
    {"sku_id": "SKU_1001", "name": "内六角螺丝", "spec": "M6x20", "brand": "Generic", "material": "304不锈钢"},
    {"sku_id": "SKU_1002", "name": "内六角螺丝", "spec": "M8x25", "brand": "Generic", "material": "碳钢"},
    {"sku_id": "SKU_1003", "name": "平垫圈", "spec": "M6", "brand": "Generic", "material": "304不锈钢"},
    {"sku_id": "SKU_1004", "name": "弹簧垫圈", "spec": "M6", "brand": "Generic", "material": "65Mn"},
    {"sku_id": "SKU_1005", "name": "六角螺母", "spec": "M6", "brand": "Generic", "material": "碳钢"},
    {"sku_id": "SKU_1006", "name": "管子割刀", "spec": "M8", "brand": "Generic", "material": "碳钢"},
    {"sku_id": "SKU_1007", "name": "手锯", "spec": "M10", "brand": "Generic", "material": "碳钢"},
    {"sku_id": "SKU_1008", "name": "钳子", "spec": "M10", "brand": "Generic", "material": "碳钢"},
    {"sku_id": "SKU_1010", "name": "锤子", "spec": "银色锤头", "brand": "Generic", "material": "塑料"},
    {"sku_id": "SKU_1011", "name": "锤子", "spec": "黄色锤头", "brand": "Generic", "material": "塑料"},
    {"sku_id": "SKU_1012", "name": "锤子", "spec": "红色锤头", "brand": "Generic", "material": "塑料"},
    {"sku_id": "SKU_1013", "name": "锤子", "spec": "黑色锤头", "brand": "Generic", "material": "塑料"},
    {"sku_id": "SKU_1014", "name": "锤子", "spec": "蓝色锤头", "brand": "Generic", "material": "塑料"},
    {"sku_id": "SKU_1015", "name": "锤子", "spec": "银色锤头", "brand": "Generic", "material": "碳钢"},
    {"sku_id": "SKU_1016", "name": "锤子", "spec": "黄色锤头", "brand": "Generic", "material": "碳钢"},
    {"sku_id": "SKU_1017", "name": "锤子", "spec": "红色锤头", "brand": "Generic", "material": "碳钢"},
    {"sku_id": "SKU_1018", "name": "锤子", "spec": "黑色锤头", "brand": "Generic", "material": "碳钢"},
    {"sku_id": "SKU_1019", "name": "锤子", "spec": "蓝色锤头", "brand": "Generic", "material": "碳钢"},
    {"sku_id": "SKU_1020", "name": "螺丝刀", "spec": "黄色手柄", "brand": "Generic", "material": "塑料"},
    {"sku_id": "SKU_1021", "name": "螺丝刀", "spec": "黑色手柄", "brand": "Generic", "material": "塑料"},
    {"sku_id": "SKU_1022", "name": "螺丝刀", "spec": "红色手柄", "brand": "Generic", "material": "塑料"},
    {"sku_id": "SKU_1023", "name": "螺丝刀", "spec": "蓝色手柄", "brand": "Generic", "material": "塑料"},
    {"sku_id": "SKU_1024", "name": "螺丝刀", "spec": "绿色手柄", "brand": "Generic", "material": "塑料"},
    {"sku_id": "SKU_1025", "name": "螺丝刀", "spec": "紫色手柄", "brand": "Generic", "material": "金属"},
    {"sku_id": "SKU_1026", "name": "螺丝刀", "spec": "粉色手柄", "brand": "Generic", "material": "金属"},
    {"sku_id": "SKU_1027", "name": "螺丝刀", "spec": "灰色手柄", "brand": "Generic", "material": "金属"},
    {"sku_id": "SKU_1028", "name": "螺丝刀", "spec": "棕色手柄", "brand": "Generic", "material": "金属"},
    {"sku_id": "SKU_1029", "name": "螺丝刀", "spec": "青色手柄", "brand": "Generic", "material": "金属"},
]

MOCK_INVENTORY = {
    "SKU_1001": {"qty_available": 120, "warehouse_id": "WH_A", "updated_at": "2026-03-23 10:00:00"},
    "SKU_1002": {"qty_available": 0, "warehouse_id": "WH_A", "updated_at": "2026-03-23 10:00:00"},
    "SKU_1003": {"qty_available": 330, "warehouse_id": "WH_B", "updated_at": "2026-03-23 10:05:00"},
    "SKU_1004": {"qty_available": 56, "warehouse_id": "WH_B", "updated_at": "2026-03-23 10:05:00"},
    "SKU_1005": {"qty_available": 21, "warehouse_id": "WH_A", "updated_at": "2026-03-23 10:00:00"},
}

NAME_ALIAS = {
    "内六角螺栓": "内六角螺丝",
    "内六角螺钉": "内六角螺丝",
    "平垫": "平垫圈",
    "弹垫": "弹簧垫圈",
    "六角母": "六角螺母",
    "管子割刀": "管子割刀",
    "手锯": "手锯",
    "钳子": "钳子",
    "锤子": "锤子",
    "螺丝刀": "螺丝刀",
}
