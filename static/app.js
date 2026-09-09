const state = {
  categories: [],
  containers: [],
  items: [],
  selectedContainerId: null,
  editingItemId: null,
  searchTerm: "",
};

const elements = {
  containerCount: document.querySelector("#containerCount"),
  itemCount: document.querySelector("#itemCount"),
  unitCount: document.querySelector("#unitCount"),
  searchInput: document.querySelector("#searchInput"),
  showCategoryPanel: document.querySelector("#showCategoryPanel"),
  showAddContainer: document.querySelector("#showAddContainer"),
  printMultipleQr: document.querySelector("#printMultipleQr"),
  printSelectDialog: document.querySelector("#printSelectDialog"),
  printSelectForm: document.querySelector("#printSelectForm"),
  printSelectList: document.querySelector("#printSelectList"),
  printSelectAll: document.querySelector("#printSelectAll"),
  printSelectNone: document.querySelector("#printSelectNone"),
  cancelPrintSelectDialog: document.querySelector("#cancelPrintSelectDialog"),
  message: document.querySelector("#message"),
  categoryPanel: document.querySelector("#categoryPanel"),
  categoryForm: document.querySelector("#categoryForm"),
  categoryId: document.querySelector("#categoryId"),
  categoryName: document.querySelector("#categoryName"),
  cancelCategoryForm: document.querySelector("#cancelCategoryForm"),
  categories: document.querySelector("#categories"),
  containerFormPanel: document.querySelector("#containerFormPanel"),
  containerForm: document.querySelector("#containerForm"),
  containerId: document.querySelector("#containerId"),
  containerName: document.querySelector("#containerName"),
  containerCategory: document.querySelector("#containerCategory"),
  containerDescription: document.querySelector("#containerDescription"),
  cancelContainerForm: document.querySelector("#cancelContainerForm"),
  containers: document.querySelector("#containers"),
  emptyState: document.querySelector("#emptyState"),
  detailPanel: document.querySelector("#detailPanel"),
  detailName: document.querySelector("#detailName"),
  detailCategory: document.querySelector("#detailCategory"),
  detailDescription: document.querySelector("#detailDescription"),
  selectedSummary: document.querySelector("#selectedSummary"),
  searchResultsPanel: document.querySelector("#searchResultsPanel"),
  searchResultsSummary: document.querySelector("#searchResultsSummary"),
  searchResults: document.querySelector("#searchResults"),
  editContainer: document.querySelector("#editContainer"),
  deleteContainer: document.querySelector("#deleteContainer"),
  qrImage: document.querySelector("#qrImage"),
  qrUrl: document.querySelector("#qrUrl"),
  openQrUrl: document.querySelector("#openQrUrl"),
  copyQrUrl: document.querySelector("#copyQrUrl"),
  printQr: document.querySelector("#printQr"),
  itemForm: document.querySelector("#itemForm"),
  itemId: document.querySelector("#itemId"),
  itemName: document.querySelector("#itemName"),
  itemQuantity: document.querySelector("#itemQuantity"),
  itemNotes: document.querySelector("#itemNotes"),
  cancelItemForm: document.querySelector("#cancelItemForm"),
  items: document.querySelector("#items"),
};

async function request(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || "Something went wrong");
  }
  return data;
}

async function loadInventory() {
  const data = await request("/api/inventory");
  state.categories = data.categories || [];
  state.containers = data.containers;
  state.items = data.items;
  const linkedToken = tokenFromPath();
  const linkedContainer = linkedToken
    ? state.containers.find((container) => container.qr_token === linkedToken)
    : null;

  if (linkedContainer) {
    state.selectedContainerId = linkedContainer.id;
  } else if (linkedToken) {
    state.selectedContainerId = null;
    showMessage("Container link not found");
  } else if (!state.selectedContainerId && state.containers.length > 0) {
    state.selectedContainerId = state.containers[0].id;
  }
  if (!linkedToken && !state.containers.some((container) => container.id === state.selectedContainerId)) {
    state.selectedContainerId = state.containers[0]?.id || null;
  }
  render();
}

function render() {
  renderStats();
  renderCategoryOptions();
  renderCategories();
  renderContainers();
  renderDetails();
}

function renderStats() {
  const totalQuantity = state.items.reduce((sum, item) => sum + Number(item.quantity), 0);
  elements.containerCount.textContent = state.containers.length;
  elements.itemCount.textContent = state.items.length;
  elements.unitCount.textContent = totalQuantity;
}

function renderContainers() {
  const containers = filteredContainers();

  if (state.containers.length === 0) {
    elements.containers.innerHTML = `<div class="muted-empty">No containers yet.</div>`;
    return;
  }
  if (containers.length === 0) {
    elements.containers.innerHTML = `<div class="muted-empty">No matching containers.</div>`;
    return;
  }

  elements.containers.innerHTML = containers
    .map(
      (container) => `
        <button class="container-card ${container.id === state.selectedContainerId ? "active" : ""}" data-container-id="${container.id}" type="button">
          <h3>${escapeHtml(container.name)}</h3>
          ${container.description ? `<p>${escapeHtml(container.description)}</p>` : ""}
          <div class="card-meta">
            ${
              container.category_name
                ? `<span class="container-category-chip">${escapeHtml(container.category_name)}</span>`
                : ""
            }
            <span>${container.item_count} item types</span>
            <span>${container.total_quantity} units</span>
          </div>
        </button>
      `
    )
    .join("");

  document.querySelectorAll("[data-container-id]").forEach((button) => {
    button.addEventListener("click", () => {
      state.selectedContainerId = Number(button.dataset.containerId);
      updateSelectedUrl();
      resetItemForm();
      render();
    });
  });
}

function renderDetails() {
  const container = selectedContainer();
  if (!container) {
    elements.emptyState.classList.remove("hidden");
    elements.detailPanel.classList.add("hidden");
    renderSearchResults();
    return;
  }

  const items = selectedItems();
  const totalQuantity = items.reduce((sum, item) => sum + Number(item.quantity), 0);
  elements.emptyState.classList.add("hidden");
  elements.detailPanel.classList.remove("hidden");
  elements.detailName.textContent = container.name;
  if (container.category_name) {
    elements.detailCategory.textContent = container.category_name;
    elements.detailCategory.classList.remove("hidden");
  } else {
    elements.detailCategory.textContent = "";
    elements.detailCategory.classList.add("hidden");
  }
  elements.detailDescription.textContent = container.description || "No description";
  elements.selectedSummary.textContent = `${items.length} item types, ${totalQuantity} units`;
  elements.qrImage.src = `/api/containers/${container.id}/qr.svg`;
  elements.qrImage.alt = `QR code for ${container.name}`;
  elements.qrUrl.value = containerDeepLink(container);

  if (items.length === 0) {
    elements.items.innerHTML = `<div class="muted-empty">No items in this container yet.</div>`;
    renderSearchResults();
    return;
  }

  elements.items.innerHTML = items
    .map(
      (item) => `
        <article class="item-row">
          <div>
            <h3>${escapeHtml(item.name)}</h3>
            ${item.notes ? `<p>${escapeHtml(item.notes)}</p>` : ""}
          </div>
          <span class="quantity-pill">${item.quantity}</span>
          <p>${escapeHtml(item.container_name)}</p>
          <div class="row-actions">
            <button class="ghost-button" data-edit-item="${item.id}" type="button">Edit</button>
            <button class="danger-button" data-delete-item="${item.id}" type="button">Delete</button>
          </div>
        </article>
      `
    )
    .join("");

  document.querySelectorAll("[data-edit-item]").forEach((button) => {
    button.addEventListener("click", () => startEditItem(Number(button.dataset.editItem)));
  });
  document.querySelectorAll("[data-delete-item]").forEach((button) => {
    button.addEventListener("click", () => deleteItem(Number(button.dataset.deleteItem)));
  });
  renderSearchResults();
}

function selectedContainer() {
  return state.containers.find((container) => container.id === state.selectedContainerId);
}

function selectedItems() {
  return state.items
    .filter((item) => item.container_id === state.selectedContainerId)
    .sort((a, b) => a.name.localeCompare(b.name));
}

function normalizedSearchTerm() {
  return state.searchTerm.trim().toLowerCase();
}

function textMatchesSearch(value, term = normalizedSearchTerm()) {
  return String(value || "").toLowerCase().includes(term);
}

function itemMatchesSearch(item, term = normalizedSearchTerm()) {
  return [item.name, item.notes, item.container_name].some((value) =>
    textMatchesSearch(value, term)
  );
}

function containerMatchesSearch(container, term = normalizedSearchTerm()) {
  const ownMatch = [container.name, container.description, container.category_name].some((value) =>
    textMatchesSearch(value, term)
  );
  const itemMatch = state.items.some(
    (item) => item.container_id === container.id && itemMatchesSearch(item, term)
  );
  return ownMatch || itemMatch;
}

function filteredContainers() {
  const term = normalizedSearchTerm();
  if (!term) return state.containers;
  return state.containers.filter((container) => containerMatchesSearch(container, term));
}

function matchingItems() {
  const term = normalizedSearchTerm();
  if (!term) return [];
  return state.items
    .filter((item) => itemMatchesSearch(item, term))
    .sort((a, b) => {
      const containerCompare = a.container_name.localeCompare(b.container_name);
      return containerCompare || a.name.localeCompare(b.name);
    });
}

function renderSearchResults() {
  const term = normalizedSearchTerm();
  if (!term) {
    elements.searchResultsPanel.classList.add("hidden");
    elements.searchResults.innerHTML = "";
    elements.searchResultsSummary.textContent = "";
    return;
  }

  const items = matchingItems();
  elements.searchResultsPanel.classList.remove("hidden");
  elements.searchResultsSummary.textContent = `${items.length} matches`;

  if (items.length === 0) {
    elements.searchResults.innerHTML = `<div class="muted-empty">No matching items.</div>`;
    return;
  }

  elements.searchResults.innerHTML = items
    .map(
      (item) => `
        <button class="search-result-row" data-result-container-id="${item.container_id}" type="button">
          <span class="search-result-main">
            <strong>${escapeHtml(item.name)}</strong>
            ${item.notes ? `<span>${escapeHtml(item.notes)}</span>` : ""}
          </span>
          <span class="quantity-pill">${item.quantity}</span>
          <span class="search-result-location">${escapeHtml(item.container_name)}</span>
        </button>
      `
    )
    .join("");

  document.querySelectorAll("[data-result-container-id]").forEach((button) => {
    button.addEventListener("click", () => {
      state.selectedContainerId = Number(button.dataset.resultContainerId);
      updateSelectedUrl();
      resetItemForm();
      render();
    });
  });
}

function renderCategoryOptions() {
  const selectedValue = elements.containerCategory.value;
  elements.containerCategory.innerHTML = [
    `<option value="">No category</option>`,
    ...state.categories.map(
      (category) => `<option value="${category.id}">${escapeHtml(category.name)}</option>`
    ),
  ].join("");
  if (state.categories.some((category) => String(category.id) === selectedValue)) {
    elements.containerCategory.value = selectedValue;
  }
}

function renderCategories() {
  if (state.categories.length === 0) {
    elements.categories.innerHTML = `<div class="muted-empty">No categories yet.</div>`;
    return;
  }

  elements.categories.innerHTML = state.categories
    .map((category) => {
      const count = state.containers.filter((container) => container.category_id === category.id).length;
      return `
        <article class="category-row">
          <div>
            <h3>${escapeHtml(category.name)}</h3>
            <p>${count} containers</p>
          </div>
          <div class="row-actions">
            <button class="ghost-button" data-edit-category="${category.id}" type="button">Edit</button>
            <button class="danger-button" data-delete-category="${category.id}" type="button">Delete</button>
          </div>
        </article>
      `;
    })
    .join("");

  document.querySelectorAll("[data-edit-category]").forEach((button) => {
    button.addEventListener("click", () => startEditCategory(Number(button.dataset.editCategory)));
  });
  document.querySelectorAll("[data-delete-category]").forEach((button) => {
    button.addEventListener("click", () => deleteCategory(Number(button.dataset.deleteCategory)));
  });
}

function tokenFromPath() {
  const match = window.location.pathname.match(/^\/container\/([^/]+)$/);
  return match ? decodeURIComponent(match[1]) : null;
}

function containerDeepLink(container) {
  return `${window.location.origin}/container/${encodeURIComponent(container.qr_token)}`;
}

function updateSelectedUrl() {
  const container = selectedContainer();
  if (!container) return;
  window.history.pushState({}, "", `/container/${encodeURIComponent(container.qr_token)}`);
}

function showMessage(text = "") {
  elements.message.textContent = text;
}

function showContainerForm(container = null) {
  elements.containerFormPanel.classList.remove("hidden");
  elements.containerId.value = container?.id || "";
  elements.containerName.value = container?.name || "";
  elements.containerCategory.value = container?.category_id || "";
  elements.containerDescription.value = container?.description || "";
  elements.containerName.focus();
}

function hideContainerForm() {
  elements.containerFormPanel.classList.add("hidden");
  elements.containerForm.reset();
  elements.containerId.value = "";
  elements.containerCategory.value = "";
}

function toggleCategoryPanel() {
  elements.categoryPanel.classList.toggle("hidden");
  if (!elements.categoryPanel.classList.contains("hidden")) {
    elements.categoryName.focus();
  }
}

function resetCategoryForm() {
  elements.categoryForm.reset();
  elements.categoryId.value = "";
}

function startEditCategory(categoryId) {
  const category = state.categories.find((candidate) => candidate.id === categoryId);
  if (!category) return;
  elements.categoryPanel.classList.remove("hidden");
  elements.categoryId.value = category.id;
  elements.categoryName.value = category.name;
  elements.categoryName.focus();
}

function startEditItem(itemId) {
  const item = state.items.find((candidate) => candidate.id === itemId);
  if (!item) return;
  state.editingItemId = item.id;
  elements.itemId.value = item.id;
  elements.itemName.value = item.name;
  elements.itemQuantity.value = item.quantity;
  elements.itemNotes.value = item.notes;
  elements.cancelItemForm.classList.remove("hidden");
  elements.itemName.focus();
}

function resetItemForm() {
  state.editingItemId = null;
  elements.itemForm.reset();
  elements.itemQuantity.value = 1;
  elements.itemId.value = "";
  elements.cancelItemForm.classList.add("hidden");
}

async function saveContainer(event) {
  event.preventDefault();
  showMessage();
  const id = elements.containerId.value;
  const payload = {
    name: elements.containerName.value,
    category_id: elements.containerCategory.value,
    description: elements.containerDescription.value,
  };
  try {
    const saved = await request(id ? `/api/containers/${id}` : "/api/containers", {
      method: id ? "PUT" : "POST",
      body: JSON.stringify(payload),
    });
    state.selectedContainerId = saved.id;
    window.history.pushState({}, "", `/container/${encodeURIComponent(saved.qr_token)}`);
    hideContainerForm();
    await loadInventory();
  } catch (error) {
    showMessage(error.message);
  }
}

async function saveCategory(event) {
  event.preventDefault();
  showMessage();
  const id = elements.categoryId.value;
  const payload = { name: elements.categoryName.value };

  try {
    await request(id ? `/api/categories/${id}` : "/api/categories", {
      method: id ? "PUT" : "POST",
      body: JSON.stringify(payload),
    });
    resetCategoryForm();
    await loadInventory();
  } catch (error) {
    showMessage(error.message);
  }
}

async function deleteCategory(categoryId) {
  const category = state.categories.find((candidate) => candidate.id === categoryId);
  if (!category) return;
  const containerCount = state.containers.filter((container) => container.category_id === category.id).length;
  const confirmed = window.confirm(
    `Delete "${category.name}"? ${containerCount} containers will be moved to no category.`
  );
  if (!confirmed) return;
  try {
    await request(`/api/categories/${categoryId}`, { method: "DELETE" });
    resetCategoryForm();
    await loadInventory();
  } catch (error) {
    showMessage(error.message);
  }
}

async function saveItem(event) {
  event.preventDefault();
  const container = selectedContainer();
  if (!container) return;

  showMessage();
  const id = elements.itemId.value;
  const payload = {
    name: elements.itemName.value,
    quantity: elements.itemQuantity.value,
    notes: elements.itemNotes.value,
  };

  try {
    await request(id ? `/api/items/${id}` : `/api/containers/${container.id}/items`, {
      method: id ? "PUT" : "POST",
      body: JSON.stringify(payload),
    });
    resetItemForm();
    await loadInventory();
  } catch (error) {
    showMessage(error.message);
  }
}

async function deleteSelectedContainer() {
  const container = selectedContainer();
  if (!container) return;
  const confirmed = window.confirm(`Delete "${container.name}" and all items inside it?`);
  if (!confirmed) return;
  try {
    await request(`/api/containers/${container.id}`, { method: "DELETE" });
    state.selectedContainerId = null;
    window.history.pushState({}, "", "/");
    await loadInventory();
  } catch (error) {
    showMessage(error.message);
  }
}

function openQrUrl() {
  const container = selectedContainer();
  if (!container) return;
  window.open(containerDeepLink(container), "_blank", "noopener");
}

async function copyQrUrl() {
  const container = selectedContainer();
  if (!container) return;
  const url = containerDeepLink(container);
  try {
    await navigator.clipboard.writeText(url);
    showMessage("Copied URL");
  } catch (error) {
    elements.qrUrl.select();
    document.execCommand("copy");
    showMessage("Copied URL");
  }
}

function printQr() {
  const container = selectedContainer();
  if (!container) return;
  window.open(`/print/${encodeURIComponent(container.qr_token)}`, "_blank", "noopener");
}

function sortedContainersForPrint() {
  return [...state.containers].sort((a, b) =>
    a.name.localeCompare(b.name, undefined, { sensitivity: "base" })
  );
}

function openPrintSelectDialog() {
  const containers = sortedContainersForPrint();
  if (containers.length === 0) {
    showMessage("Add containers before printing QR labels");
    return;
  }

  elements.printSelectList.innerHTML = containers
    .map(
      (container) => `
        <label class="print-select-row">
          <input type="checkbox" name="printContainerId" value="${container.id}" checked />
          <span>${escapeHtml(container.name)}${
        container.category_name ? ` <span class="print-select-category">${escapeHtml(container.category_name)}</span>` : ""
      }</span>
        </label>`
    )
    .join("");

  elements.printSelectDialog.showModal();
}

function setAllPrintCheckboxes(checked) {
  elements.printSelectList
    .querySelectorAll('input[name="printContainerId"]')
    .forEach((checkbox) => {
      checkbox.checked = checked;
    });
}

function printSelectedQr(event) {
  event.preventDefault();
  const ids = Array.from(
    elements.printSelectList.querySelectorAll('input[name="printContainerId"]:checked')
  ).map((checkbox) => checkbox.value);

  if (ids.length === 0) {
    showMessage("Select at least one container to print");
    return;
  }

  elements.printSelectDialog.close();
  window.open(`/print-all?ids=${ids.join(",")}`, "_blank", "noopener");
}

async function deleteItem(itemId) {
  const item = state.items.find((candidate) => candidate.id === itemId);
  if (!item) return;
  const confirmed = window.confirm(`Delete "${item.name}"?`);
  if (!confirmed) return;
  try {
    await request(`/api/items/${itemId}`, { method: "DELETE" });
    await loadInventory();
  } catch (error) {
    showMessage(error.message);
  }
}

function applyLocalSearch() {
  state.searchTerm = elements.searchInput.value;
  render();
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

elements.showCategoryPanel.addEventListener("click", toggleCategoryPanel);
elements.showAddContainer.addEventListener("click", () => showContainerForm());
elements.printMultipleQr.addEventListener("click", openPrintSelectDialog);
elements.printSelectAll.addEventListener("click", () => setAllPrintCheckboxes(true));
elements.printSelectNone.addEventListener("click", () => setAllPrintCheckboxes(false));
elements.printSelectForm.addEventListener("submit", printSelectedQr);
elements.cancelPrintSelectDialog.addEventListener("click", () => elements.printSelectDialog.close());
elements.categoryForm.addEventListener("submit", saveCategory);
elements.cancelCategoryForm.addEventListener("click", resetCategoryForm);
elements.cancelContainerForm.addEventListener("click", hideContainerForm);
elements.containerForm.addEventListener("submit", saveContainer);
elements.editContainer.addEventListener("click", () => showContainerForm(selectedContainer()));
elements.deleteContainer.addEventListener("click", deleteSelectedContainer);
elements.openQrUrl.addEventListener("click", openQrUrl);
elements.copyQrUrl.addEventListener("click", copyQrUrl);
elements.printQr.addEventListener("click", printQr);
elements.itemForm.addEventListener("submit", saveItem);
elements.cancelItemForm.addEventListener("click", resetItemForm);
elements.searchInput.addEventListener("input", applyLocalSearch);
window.addEventListener("popstate", loadInventory);

loadInventory().catch((error) => showMessage(error.message));
