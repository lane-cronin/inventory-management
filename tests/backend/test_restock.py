"""
Tests for restock API endpoints (recommendations and orders).
"""
import re

import pytest


class TestRestockRecommendationsEndpoint:
    """Test suite for GET /api/restock/recommendations."""

    def test_get_recommendations_success(self, client):
        """Test getting recommendations returns proper structure."""
        response = client.get("/api/restock/recommendations?budget=50000")
        assert response.status_code == 200

        data = response.json()
        assert data["budget"] == 50000
        assert isinstance(data["recommendations"], list)
        assert len(data["recommendations"]) > 0
        assert isinstance(data["skipped_skus"], list)

        first = data["recommendations"][0]
        for field in [
            "sku", "item_name", "category", "warehouse", "quantity_on_hand",
            "reorder_point", "forecasted_demand", "recommended_quantity",
            "unit_cost", "total_cost", "urgency_score", "urgency", "trend",
            "lead_time_days", "selected",
        ]:
            assert field in first

    def test_recommendations_sorted_by_urgency(self, client):
        """Test recommendations are ranked most urgent first."""
        response = client.get("/api/restock/recommendations?budget=50000")
        data = response.json()

        scores = [rec["urgency_score"] for rec in data["recommendations"]]
        assert scores == sorted(scores, reverse=True)

    def test_recommendations_zero_budget_selects_nothing(self, client):
        """Test budget=0 returns candidates but selects none."""
        response = client.get("/api/restock/recommendations?budget=0")
        assert response.status_code == 200

        data = response.json()
        assert len(data["recommendations"]) > 0
        assert all(not rec["selected"] for rec in data["recommendations"])
        assert data["total_cost"] == 0
        assert data["remaining_budget"] == 0

    def test_recommendations_large_budget_selects_all(self, client):
        """Test a budget above the full restock cost selects every candidate."""
        response = client.get("/api/restock/recommendations?budget=1000000")
        data = response.json()

        assert all(rec["selected"] for rec in data["recommendations"])
        full_cost = sum(rec["total_cost"] for rec in data["recommendations"])
        assert abs(data["total_cost"] - full_cost) < 0.01

    def test_recommendations_selection_within_budget(self, client):
        """Test selected items never exceed the budget."""
        response = client.get("/api/restock/recommendations?budget=50000")
        data = response.json()

        selected_cost = sum(
            rec["total_cost"] for rec in data["recommendations"] if rec["selected"]
        )
        assert selected_cost <= 50000
        assert abs(data["total_cost"] - selected_cost) < 0.01
        assert abs(data["remaining_budget"] - (50000 - selected_cost)) < 0.01

    def test_recommendations_quantity_formula(self, client):
        """Test recommended quantity = forecast + reorder point - on hand."""
        response = client.get("/api/restock/recommendations?budget=50000")
        data = response.json()

        # Cross-check against the raw demand and inventory endpoints
        demand = {f["item_sku"]: f for f in client.get("/api/demand").json()}
        inventory = {i["sku"]: i for i in client.get("/api/inventory").json()}

        for rec in data["recommendations"]:
            forecast = demand[rec["sku"]]
            inv = inventory[rec["sku"]]
            expected_qty = (
                forecast["forecasted_demand"] + inv["reorder_point"]
                - inv["quantity_on_hand"]
            )
            assert rec["recommended_quantity"] == expected_qty
            assert rec["recommended_quantity"] > 0
            assert abs(
                rec["total_cost"] - rec["recommended_quantity"] * inv["unit_cost"]
            ) < 0.01

    def test_recommendations_urgency_values(self, client):
        """Test urgency labels match their score thresholds."""
        response = client.get("/api/restock/recommendations?budget=50000")
        data = response.json()

        for rec in data["recommendations"]:
            assert 0 <= rec["urgency_score"] <= 1
            if rec["urgency_score"] >= 0.6:
                assert rec["urgency"] == "high"
            elif rec["urgency_score"] >= 0.3:
                assert rec["urgency"] == "medium"
            else:
                assert rec["urgency"] == "low"

    def test_recommendations_missing_budget(self, client):
        """Test missing budget parameter returns validation error."""
        response = client.get("/api/restock/recommendations")
        assert response.status_code == 422

    def test_recommendations_negative_budget(self, client):
        """Test negative budget returns validation error."""
        response = client.get("/api/restock/recommendations?budget=-100")
        assert response.status_code == 422


class TestRestockOrdersEndpoints:
    """Test suite for POST/GET /api/restock/orders."""

    def test_create_restock_order_success(self, client):
        """Test submitting a restock order returns the created order."""
        payload = {
            "budget": 50000,
            "items": [
                {"sku": "SNR-420", "quantity": 202},
                {"sku": "CTL-330", "quantity": 116},
            ],
        }
        response = client.post("/api/restock/orders", json=payload)
        assert response.status_code == 201

        order = response.json()
        assert re.match(r"^RST-\d{4}-\d{4}$", order["order_number"])
        assert order["status"] == "Submitted"
        assert order["budget"] == 50000
        assert len(order["items"]) == 2

        # Lead times come from the category map: Sensors=7, Controllers=21
        leads = {item["sku"]: item["lead_time_days"] for item in order["items"]}
        assert leads["SNR-420"] == 7
        assert leads["CTL-330"] == 21
        assert order["max_lead_time_days"] == 21

        # Line and order totals derive from inventory unit costs
        expected_total = 202 * 72.50 + 116 * 54.25
        assert abs(order["total_cost"] - expected_total) < 0.01

    def test_create_order_expected_delivery(self, client):
        """Test expected delivery reflects the max lead time from order date."""
        from datetime import datetime, timedelta

        payload = {"budget": 10000, "items": [{"sku": "SNR-420", "quantity": 10}]}
        response = client.post("/api/restock/orders", json=payload)
        order = response.json()

        order_date = datetime.fromisoformat(order["order_date"])
        expected = datetime.strptime(order["expected_delivery"], "%Y-%m-%d")
        # Sensors lead time is 7 days; compare dates only to avoid time-of-day drift
        assert expected.date() == (order_date + timedelta(days=7)).date()

    def test_get_restock_orders_count_grows(self, client):
        """Test GET list grows by exactly one after a POST."""
        # Module-level list persists across tests, so assert relative growth only
        before = len(client.get("/api/restock/orders").json())

        payload = {"budget": 5000, "items": [{"sku": "PSU-501", "quantity": 5}]}
        response = client.post("/api/restock/orders", json=payload)
        assert response.status_code == 201

        after_list = client.get("/api/restock/orders").json()
        assert len(after_list) == before + 1
        assert after_list[-1]["order_number"] == response.json()["order_number"]

    def test_order_numbers_increment(self, client):
        """Test sequential orders get incrementing order numbers."""
        payload = {"budget": 5000, "items": [{"sku": "PSU-501", "quantity": 1}]}
        first = client.post("/api/restock/orders", json=payload).json()
        second = client.post("/api/restock/orders", json=payload).json()

        first_seq = int(first["order_number"].split("-")[-1])
        second_seq = int(second["order_number"].split("-")[-1])
        assert second_seq == first_seq + 1

    def test_create_order_unknown_sku(self, client):
        """Test unknown SKU returns 404 naming the SKU."""
        payload = {"budget": 5000, "items": [{"sku": "FAKE-999", "quantity": 5}]}
        response = client.post("/api/restock/orders", json=payload)
        assert response.status_code == 404
        assert "FAKE-999" in response.json()["detail"]

    def test_create_order_empty_items(self, client):
        """Test empty items list returns 400."""
        response = client.post(
            "/api/restock/orders", json={"budget": 5000, "items": []}
        )
        assert response.status_code == 400
        assert "detail" in response.json()

    def test_create_order_duplicate_skus(self, client):
        """Test duplicate SKUs in one order returns 400."""
        payload = {
            "budget": 5000,
            "items": [
                {"sku": "PSU-501", "quantity": 5},
                {"sku": "PSU-501", "quantity": 3},
            ],
        }
        response = client.post("/api/restock/orders", json=payload)
        assert response.status_code == 400
        assert "duplicate" in response.json()["detail"].lower()

    def test_create_order_zero_quantity(self, client):
        """Test zero quantity fails Pydantic validation."""
        payload = {"budget": 5000, "items": [{"sku": "PSU-501", "quantity": 0}]}
        response = client.post("/api/restock/orders", json=payload)
        assert response.status_code == 422

    def test_create_order_negative_budget(self, client):
        """Test negative budget fails Pydantic validation."""
        payload = {"budget": -1, "items": [{"sku": "PSU-501", "quantity": 5}]}
        response = client.post("/api/restock/orders", json=payload)
        assert response.status_code == 422
