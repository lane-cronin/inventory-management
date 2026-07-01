<template>
  <div class="restocking">
    <div class="page-header">
      <h2>{{ t('restocking.title') }}</h2>
      <p>{{ t('restocking.description') }}</p>
    </div>

    <!-- Full-page loading only for the initial fetch; budget refetches keep the table mounted -->
    <div v-if="loading && !data" class="loading">{{ t('common.loading') }}</div>
    <div v-else-if="error" class="error">{{ error }}</div>
    <div v-else-if="data">
      <div v-if="successOrder" class="success-banner">
        <span>{{ t('restocking.orderPlaced', { orderNumber: successOrder.order_number }) }}</span>
        <router-link to="/orders" class="success-link">{{ t('restocking.viewOrders') }}</router-link>
      </div>

      <div class="card">
        <label class="budget-label" for="budget-slider">{{ t('restocking.budgetLabel') }}</label>
        <div class="budget-controls">
          <input
            id="budget-slider"
            type="range"
            min="0"
            max="200000"
            step="5000"
            v-model.number="budget"
            class="budget-slider"
          />
          <span class="budget-value">{{ fmt(budget) }}</span>
        </div>
      </div>

      <div class="stats-grid">
        <div class="stat-card">
          <div class="stat-label">{{ t('restocking.budgetLabel') }}</div>
          <div class="stat-value">{{ fmt(budget) }}</div>
        </div>
        <div class="stat-card info">
          <div class="stat-label">{{ t('restocking.plannedSpend') }}</div>
          <div class="stat-value">{{ fmt(data.total_cost) }}</div>
        </div>
        <div class="stat-card success">
          <div class="stat-label">{{ t('restocking.remainingBudget') }}</div>
          <div class="stat-value">{{ fmt(data.remaining_budget) }}</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">{{ t('restocking.itemsSelected') }}</div>
          <div class="stat-value">{{ selectedItems.length }}</div>
        </div>
      </div>

      <div class="card">
        <div class="card-header">
          <h3 class="card-title">{{ t('restocking.recommendationsTitle') }}</h3>
        </div>

        <div v-if="data.recommendations.length === 0" class="no-recommendations">
          {{ t('restocking.noRecommendations') }}
        </div>

        <div v-else class="table-container">
          <table>
            <thead>
              <tr>
                <th>{{ t('restocking.table.sku') }}</th>
                <th>{{ t('restocking.table.itemName') }}</th>
                <th>{{ t('restocking.table.category') }}</th>
                <th>{{ t('restocking.table.warehouse') }}</th>
                <th>{{ t('restocking.table.onHand') }}</th>
                <th>{{ t('restocking.table.recommendedQty') }}</th>
                <th>{{ t('restocking.table.unitCost') }}</th>
                <th>{{ t('restocking.table.totalCost') }}</th>
                <th>{{ t('restocking.table.urgency') }}</th>
                <th>{{ t('restocking.table.leadTime') }}</th>
                <th>{{ t('restocking.table.budgetStatus') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="rec in data.recommendations"
                :key="rec.sku"
                :class="{ 'row-muted': !rec.selected }"
              >
                <td><strong>{{ rec.sku }}</strong></td>
                <td>{{ rec.item_name }}</td>
                <td>{{ rec.category }}</td>
                <td>{{ rec.warehouse }}</td>
                <td>{{ rec.quantity_on_hand }}</td>
                <td><strong>{{ rec.recommended_quantity }}</strong></td>
                <td>{{ fmt(rec.unit_cost) }}</td>
                <td><strong>{{ fmt(rec.total_cost) }}</strong></td>
                <td>
                  <span :class="['badge', getUrgencyClass(rec.urgency)]">
                    {{ t(`restocking.urgency.${rec.urgency}`) }}
                  </span>
                </td>
                <td>{{ t('orders.leadTimeDays', { days: rec.lead_time_days }) }}</td>
                <td>
                  <span :class="['badge', rec.selected ? 'success' : 'danger']">
                    {{ rec.selected ? t('restocking.withinBudget') : t('restocking.overBudget') }}
                  </span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <div class="order-actions">
          <button
            class="place-order-btn"
            :disabled="submitting || selectedItems.length === 0"
            @click="placeOrder"
          >
            {{ submitting ? t('restocking.submitting') : t('restocking.placeOrder') }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import { ref, computed, onMounted, watch } from 'vue'
import { api } from '../api'
import { useI18n } from '../composables/useI18n'
import { formatCurrency } from '../utils/currency'

// Note: budget planning is global and deliberately ignores the app's filter bar (no useFilters).

export default {
  name: 'Restocking',
  setup() {
    const { t, currentCurrency } = useI18n()

    const budget = ref(50000)
    const data = ref(null)
    const loading = ref(true)
    const error = ref(null)
    const submitting = ref(false)
    const successOrder = ref(null)

    const fmt = (amount) => formatCurrency(amount, currentCurrency.value)

    const selectedItems = computed(() => {
      if (!data.value) return []
      return data.value.recommendations.filter(rec => rec.selected)
    })

    const loadRecommendations = async () => {
      try {
        // Only the initial fetch (data still null) shows the full-page loading state;
        // later refetches update in place so the table never unmounts.
        if (!data.value) loading.value = true
        error.value = null
        data.value = await api.getRestockRecommendations(budget.value)
      } catch (err) {
        error.value = t('common.error') + ': ' + err.message
      } finally {
        loading.value = false
      }
    }

    // Manual 300ms debounce: slider drags fire many rapid budget updates and
    // @vueuse (watchDebounced) isn't installed, so we clear/reset a timeout ourselves.
    let debounceTimer = null
    watch(budget, () => {
      clearTimeout(debounceTimer)
      debounceTimer = setTimeout(loadRecommendations, 300)
    })

    const placeOrder = async () => {
      // Double-submit protection
      if (submitting.value) return
      try {
        submitting.value = true
        successOrder.value = null
        const order = await api.createRestockOrder({
          budget: budget.value,
          items: selectedItems.value.map(r => ({ sku: r.sku, quantity: r.recommended_quantity }))
        })
        successOrder.value = order
        // Refresh recommendations to reflect the newly placed order
        await loadRecommendations()
      } catch (err) {
        error.value = t('common.error') + ': ' + err.message
      } finally {
        submitting.value = false
      }
    }

    const getUrgencyClass = (urgency) => {
      const urgencyMap = {
        high: 'danger',
        medium: 'warning',
        low: 'success'
      }
      return urgencyMap[urgency] || 'info'
    }

    onMounted(loadRecommendations)

    return {
      t,
      budget,
      data,
      loading,
      error,
      submitting,
      successOrder,
      selectedItems,
      fmt,
      placeOrder,
      getUrgencyClass
    }
  }
}
</script>

<style scoped>
/* Budget slider */
.budget-label {
  display: block;
  font-size: 0.875rem;
  font-weight: 600;
  color: #64748b;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 0.75rem;
}

.budget-controls {
  display: flex;
  align-items: center;
  gap: 1.5rem;
}

.budget-value {
  font-size: 1.25rem;
  font-weight: 700;
  color: #0f172a;
  min-width: 110px;
  text-align: right;
  flex-shrink: 0;
}

.budget-slider {
  flex: 1;
  -webkit-appearance: none;
  appearance: none;
  height: 6px;
  background: #e2e8f0;
  border-radius: 3px;
  outline: none;
  cursor: pointer;
}

.budget-slider::-webkit-slider-runnable-track {
  height: 6px;
  background: #e2e8f0;
  border-radius: 3px;
}

.budget-slider::-webkit-slider-thumb {
  -webkit-appearance: none;
  appearance: none;
  width: 18px;
  height: 18px;
  margin-top: -6px;
  background: #3b82f6;
  border-radius: 50%;
  cursor: pointer;
  transition: background 0.2s ease;
}

.budget-slider::-webkit-slider-thumb:hover {
  background: #2563eb;
}

.budget-slider::-moz-range-track {
  height: 6px;
  background: #e2e8f0;
  border-radius: 3px;
}

.budget-slider::-moz-range-thumb {
  width: 18px;
  height: 18px;
  background: #3b82f6;
  border: none;
  border-radius: 50%;
  cursor: pointer;
  transition: background 0.2s ease;
}

.budget-slider::-moz-range-thumb:hover {
  background: #2563eb;
}

/* Rows that exceed the budget (not selected by the server-side greedy pass) */
.row-muted {
  opacity: 0.45;
}

.no-recommendations {
  text-align: center;
  padding: 3rem;
  color: #64748b;
  font-size: 0.938rem;
}

/* Place Order button */
.order-actions {
  display: flex;
  justify-content: flex-end;
  margin-top: 1rem;
  padding-top: 1rem;
  border-top: 1px solid #e2e8f0;
}

.place-order-btn {
  padding: 0.75rem 1.75rem;
  background: #3b82f6;
  color: white;
  border: none;
  border-radius: 8px;
  font-weight: 600;
  font-size: 0.938rem;
  cursor: pointer;
  transition: background 0.2s ease;
  white-space: nowrap;
}

.place-order-btn:hover:not(:disabled) {
  background: #2563eb;
}

.place-order-btn:disabled {
  background: #94a3b8;
  cursor: not-allowed;
}

/* Success banner */
.success-banner {
  display: flex;
  align-items: center;
  gap: 1rem;
  background: #d1fae5;
  border: 1px solid #6ee7b7;
  color: #065f46;
  padding: 1rem;
  border-radius: 8px;
  margin-bottom: 1.25rem;
  font-size: 0.938rem;
  font-weight: 500;
}

.success-link {
  color: #047857;
  font-weight: 600;
  text-decoration: underline;
}

.success-link:hover {
  color: #065f46;
}
</style>
