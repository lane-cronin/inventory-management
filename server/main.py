from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Optional
from pydantic import BaseModel, Field
from datetime import datetime, timedelta
from mock_data import inventory_items, orders, demand_forecasts, backlog_items, spending_summary, monthly_spending, category_spending, recent_transactions, purchase_orders, restock_orders

app = FastAPI(title="Factory Inventory Management System")

# Quarter mapping for date filtering
QUARTER_MAP = {
    'Q1-2025': ['2025-01', '2025-02', '2025-03'],
    'Q2-2025': ['2025-04', '2025-05', '2025-06'],
    'Q3-2025': ['2025-07', '2025-08', '2025-09'],
    'Q4-2025': ['2025-10', '2025-11', '2025-12']
}

# Supplier delivery lead times by category (days). Restock items not in this map
# fall back to DEFAULT_LEAD_TIME_DAYS.
CATEGORY_LEAD_TIMES = {
    'Power Supplies': 5,
    'Sensors': 7,
    'Circuit Boards': 10,
    'Actuators': 14,
    'Controllers': 21,
}
DEFAULT_LEAD_TIME_DAYS = 14

def filter_by_month(items: list, month: Optional[str]) -> list:
    """Filter items by month/quarter based on order_date field"""
    if not month or month == 'all':
        return items

    if month.startswith('Q'):
        # Handle quarters
        if month in QUARTER_MAP:
            months = QUARTER_MAP[month]
            return [item for item in items if any(m in item.get('order_date', '') for m in months)]
    else:
        # Direct month match
        return [item for item in items if month in item.get('order_date', '')]

    return items

def apply_filters(items: list, warehouse: Optional[str] = None, category: Optional[str] = None,
                 status: Optional[str] = None) -> list:
    """Apply common filters to a list of items"""
    filtered = items

    if warehouse and warehouse != 'all':
        filtered = [item for item in filtered if item.get('warehouse') == warehouse]

    if category and category != 'all':
        filtered = [item for item in filtered if item.get('category', '').lower() == category.lower()]

    if status and status != 'all':
        filtered = [item for item in filtered if item.get('status', '').lower() == status.lower()]

    return filtered

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Data models
class InventoryItem(BaseModel):
    id: str
    sku: str
    name: str
    category: str
    warehouse: str
    quantity_on_hand: int
    reorder_point: int
    unit_cost: float
    location: str
    last_updated: str

class Order(BaseModel):
    id: str
    order_number: str
    customer: str
    items: List[dict]
    status: str
    order_date: str
    expected_delivery: str
    total_value: float
    actual_delivery: Optional[str] = None
    warehouse: Optional[str] = None
    category: Optional[str] = None

class DemandForecast(BaseModel):
    id: str
    item_sku: str
    item_name: str
    current_demand: int
    forecasted_demand: int
    trend: str
    period: str

class BacklogItem(BaseModel):
    id: str
    order_id: str
    item_sku: str
    item_name: str
    quantity_needed: int
    quantity_available: int
    days_delayed: int
    priority: str
    has_purchase_order: Optional[bool] = False

class PurchaseOrder(BaseModel):
    id: str
    backlog_item_id: str
    supplier_name: str
    quantity: int
    unit_cost: float
    expected_delivery_date: str
    status: str
    created_date: str
    notes: Optional[str] = None

class CreatePurchaseOrderRequest(BaseModel):
    backlog_item_id: str
    supplier_name: str
    quantity: int
    unit_cost: float
    expected_delivery_date: str
    notes: Optional[str] = None

class RestockRecommendation(BaseModel):
    sku: str
    item_name: str
    category: str
    warehouse: str
    quantity_on_hand: int
    reorder_point: int
    forecasted_demand: int
    recommended_quantity: int
    unit_cost: float
    total_cost: float
    urgency_score: float
    urgency: str  # high | medium | low
    trend: str
    lead_time_days: int
    selected: bool  # True if this item fits within the requested budget

class RestockRecommendationsResponse(BaseModel):
    budget: float
    total_cost: float  # sum of selected items only
    remaining_budget: float
    recommendations: List[RestockRecommendation]  # all candidates ranked; UI splits on `selected`
    skipped_skus: List[str]  # forecast SKUs with no matching inventory record

class RestockOrderItemRequest(BaseModel):
    sku: str
    quantity: int = Field(gt=0)

class CreateRestockOrderRequest(BaseModel):
    budget: float = Field(ge=0)
    items: List[RestockOrderItemRequest]

class RestockOrderItem(BaseModel):
    sku: str
    item_name: str
    category: str
    warehouse: str
    quantity: int
    unit_cost: float
    total_cost: float
    lead_time_days: int
    expected_delivery: str

class RestockOrder(BaseModel):
    id: str
    order_number: str
    status: str
    order_date: str
    budget: float
    total_cost: float
    items: List[RestockOrderItem]
    max_lead_time_days: int
    expected_delivery: str

# API endpoints
@app.get("/")
def root():
    return {"message": "Factory Inventory Management System API", "version": "1.0.0"}

@app.get("/api/inventory", response_model=List[InventoryItem])
def get_inventory(
    warehouse: Optional[str] = None,
    category: Optional[str] = None
):
    """Get all inventory items with optional filtering"""
    return apply_filters(inventory_items, warehouse, category)

@app.get("/api/inventory/{item_id}", response_model=InventoryItem)
def get_inventory_item(item_id: str):
    """Get a specific inventory item"""
    item = next((item for item in inventory_items if item["id"] == item_id), None)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    return item

@app.get("/api/orders", response_model=List[Order])
def get_orders(
    warehouse: Optional[str] = None,
    category: Optional[str] = None,
    status: Optional[str] = None,
    month: Optional[str] = None
):
    """Get all orders with optional filtering"""
    filtered_orders = apply_filters(orders, warehouse, category, status)
    filtered_orders = filter_by_month(filtered_orders, month)
    return filtered_orders

@app.get("/api/orders/{order_id}", response_model=Order)
def get_order(order_id: str):
    """Get a specific order"""
    order = next((order for order in orders if order["id"] == order_id), None)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return order

@app.get("/api/demand", response_model=List[DemandForecast])
def get_demand_forecasts():
    """Get demand forecasts"""
    return demand_forecasts

@app.get("/api/backlog", response_model=List[BacklogItem])
def get_backlog():
    """Get backlog items with purchase order status"""
    # Add has_purchase_order flag to each backlog item
    result = []
    for item in backlog_items:
        item_dict = dict(item)
        # Check if this backlog item has a purchase order
        has_po = any(po["backlog_item_id"] == item["id"] for po in purchase_orders)
        item_dict["has_purchase_order"] = has_po
        result.append(item_dict)
    return result

@app.get("/api/dashboard/summary")
def get_dashboard_summary(
    warehouse: Optional[str] = None,
    category: Optional[str] = None,
    status: Optional[str] = None,
    month: Optional[str] = None
):
    """Get summary statistics for dashboard with optional filtering"""
    # Filter inventory
    filtered_inventory = apply_filters(inventory_items, warehouse, category)

    # Filter orders
    filtered_orders = apply_filters(orders, warehouse, category, status)
    filtered_orders = filter_by_month(filtered_orders, month)

    total_inventory_value = sum(item["quantity_on_hand"] * item["unit_cost"] for item in filtered_inventory)
    low_stock_items = len([item for item in filtered_inventory if item["quantity_on_hand"] <= item["reorder_point"]])
    pending_orders = len([order for order in filtered_orders if order["status"] in ["Processing", "Backordered"]])
    total_backlog_items = len(backlog_items)

    return {
        "total_inventory_value": round(total_inventory_value, 2),
        "low_stock_items": low_stock_items,
        "pending_orders": pending_orders,
        "total_backlog_items": total_backlog_items,
        "total_orders_value": sum(order["total_value"] for order in filtered_orders)
    }

@app.get("/api/spending/summary")
def get_spending_summary():
    """Get spending summary statistics"""
    return spending_summary

@app.get("/api/spending/monthly")
def get_monthly_spending():
    """Get monthly spending breakdown"""
    return monthly_spending

@app.get("/api/spending/categories")
def get_category_spending():
    """Get spending by category"""
    return category_spending

@app.get("/api/spending/transactions")
def get_recent_transactions():
    """Get recent transactions"""
    return recent_transactions

@app.get("/api/reports/quarterly")
def get_quarterly_reports():
    """Get quarterly performance reports"""
    # Calculate quarterly statistics from orders
    quarters = {}

    for order in orders:
        order_date = order.get('order_date', '')
        # Determine quarter
        if '2025-01' in order_date or '2025-02' in order_date or '2025-03' in order_date:
            quarter = 'Q1-2025'
        elif '2025-04' in order_date or '2025-05' in order_date or '2025-06' in order_date:
            quarter = 'Q2-2025'
        elif '2025-07' in order_date or '2025-08' in order_date or '2025-09' in order_date:
            quarter = 'Q3-2025'
        elif '2025-10' in order_date or '2025-11' in order_date or '2025-12' in order_date:
            quarter = 'Q4-2025'
        else:
            continue

        if quarter not in quarters:
            quarters[quarter] = {
                'quarter': quarter,
                'total_orders': 0,
                'total_revenue': 0,
                'delivered_orders': 0,
                'avg_order_value': 0
            }

        quarters[quarter]['total_orders'] += 1
        quarters[quarter]['total_revenue'] += order.get('total_value', 0)
        if order.get('status') == 'Delivered':
            quarters[quarter]['delivered_orders'] += 1

    # Calculate averages and fulfillment rate
    result = []
    for q, data in quarters.items():
        if data['total_orders'] > 0:
            data['avg_order_value'] = round(data['total_revenue'] / data['total_orders'], 2)
            data['fulfillment_rate'] = round((data['delivered_orders'] / data['total_orders']) * 100, 1)
        result.append(data)

    # Sort by quarter
    result.sort(key=lambda x: x['quarter'])
    return result

@app.get("/api/reports/monthly-trends")
def get_monthly_trends():
    """Get month-over-month trends"""
    months = {}

    for order in orders:
        order_date = order.get('order_date', '')
        if not order_date:
            continue

        # Extract month (format: YYYY-MM-DD)
        month = order_date[:7]  # Gets YYYY-MM

        if month not in months:
            months[month] = {
                'month': month,
                'order_count': 0,
                'revenue': 0,
                'delivered_count': 0
            }

        months[month]['order_count'] += 1
        months[month]['revenue'] += order.get('total_value', 0)
        if order.get('status') == 'Delivered':
            months[month]['delivered_count'] += 1

    # Convert to list and sort
    result = list(months.values())
    result.sort(key=lambda x: x['month'])
    return result

@app.get("/api/restock/recommendations", response_model=RestockRecommendationsResponse)
def get_restock_recommendations(budget: float = Query(ge=0)):
    """Recommend restock quantities from the demand forecast, ranked by urgency,
    greedily selected within the given budget."""
    # Each SKU lives in exactly one warehouse in the mock data, so a flat lookup is safe
    inv_by_sku = {item["sku"]: item for item in inventory_items}

    candidates = []
    skipped_skus = []
    for forecast in demand_forecasts:
        item = inv_by_sku.get(forecast["item_sku"])
        if not item:
            # Defensive: forecast SKUs should all exist in inventory, but don't 500 if not
            skipped_skus.append(forecast["item_sku"])
            continue

        # Stock target = expected demand plus reorder point as safety stock
        target = forecast["forecasted_demand"] + item["reorder_point"]
        recommended_quantity = max(0, target - item["quantity_on_hand"])
        if recommended_quantity == 0:
            # Already stocked past target (e.g. decreasing-demand items) — nothing to order
            continue

        # 0 = fully stocked to target, 1 = nothing on hand
        urgency_score = round(1 - item["quantity_on_hand"] / target, 3)
        if urgency_score >= 0.6:
            urgency = "high"
        elif urgency_score >= 0.3:
            urgency = "medium"
        else:
            urgency = "low"

        candidates.append({
            "sku": item["sku"],
            "item_name": item["name"],
            "category": item["category"],
            "warehouse": item["warehouse"],
            "quantity_on_hand": item["quantity_on_hand"],
            "reorder_point": item["reorder_point"],
            "forecasted_demand": forecast["forecasted_demand"],
            "recommended_quantity": recommended_quantity,
            "unit_cost": item["unit_cost"],
            "total_cost": round(recommended_quantity * item["unit_cost"], 2),
            "urgency_score": urgency_score,
            "urgency": urgency,
            "trend": forecast["trend"],
            "lead_time_days": CATEGORY_LEAD_TIMES.get(item["category"], DEFAULT_LEAD_TIME_DAYS),
            "selected": False,
        })

    # Most urgent first; among ties prefer growing demand, then bigger orders
    trend_rank = {"increasing": 0, "stable": 1, "decreasing": 2}
    candidates.sort(key=lambda c: (-c["urgency_score"], trend_rank.get(c["trend"], 1), -c["total_cost"]))

    # Greedy skip-and-continue: an item that doesn't fit is skipped, but cheaper
    # lower-urgency items after it can still be selected
    remaining = budget
    for candidate in candidates:
        if candidate["total_cost"] <= remaining:
            candidate["selected"] = True
            remaining = round(remaining - candidate["total_cost"], 2)

    total_cost = round(sum(c["total_cost"] for c in candidates if c["selected"]), 2)
    return {
        "budget": budget,
        "total_cost": total_cost,
        "remaining_budget": round(budget - total_cost, 2),
        "recommendations": candidates,
        "skipped_skus": skipped_skus,
    }

@app.post("/api/restock/orders", response_model=RestockOrder, status_code=201)
def create_restock_order(request: CreateRestockOrderRequest):
    """Submit a restocking order. Stored in memory only (resets on restart)."""
    if not request.items:
        raise HTTPException(status_code=400, detail="Order must contain at least one item")

    skus = [item.sku for item in request.items]
    if len(skus) != len(set(skus)):
        raise HTTPException(status_code=400, detail="Duplicate SKUs in order items")

    inv_by_sku = {item["sku"]: item for item in inventory_items}
    now = datetime.now()
    order_items = []
    max_lead = 0
    total_cost = 0.0
    for item_req in request.items:
        inv = inv_by_sku.get(item_req.sku)
        if not inv:
            raise HTTPException(status_code=404, detail=f"SKU {item_req.sku} not found in inventory")

        lead = CATEGORY_LEAD_TIMES.get(inv["category"], DEFAULT_LEAD_TIME_DAYS)
        max_lead = max(max_lead, lead)
        line_cost = round(item_req.quantity * inv["unit_cost"], 2)
        total_cost += line_cost
        order_items.append({
            "sku": inv["sku"],
            "item_name": inv["name"],
            "category": inv["category"],
            "warehouse": inv["warehouse"],
            "quantity": item_req.quantity,
            "unit_cost": inv["unit_cost"],
            "total_cost": line_cost,
            "lead_time_days": lead,
            "expected_delivery": (now + timedelta(days=lead)).strftime("%Y-%m-%d"),
        })

    order = {
        "id": str(len(restock_orders) + 1),
        "order_number": f"RST-{now.year}-{len(restock_orders) + 1:04d}",
        "status": "Submitted",
        "order_date": now.strftime("%Y-%m-%dT%H:%M:%S"),
        "budget": request.budget,
        "total_cost": round(total_cost, 2),
        "items": order_items,
        "max_lead_time_days": max_lead,
        # The order is complete when its slowest item arrives
        "expected_delivery": (now + timedelta(days=max_lead)).strftime("%Y-%m-%d"),
    }
    restock_orders.append(order)
    return order

@app.get("/api/restock/orders", response_model=List[RestockOrder])
def get_restock_orders():
    """Get all submitted restock orders (in-memory, newest last)"""
    return restock_orders

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
