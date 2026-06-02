// controllers/view-admin.js

(function (window, $) {
    'use strict';

    const ADMIN_CRUD_URL = 'controllers/admin-crud.php';
    const PAGE_SIZE = 10;

    let currentPage = 1;
    let totalPage = 1;
    let totalRows = 0;
    let adminRows = [];

    window.bindAdminPageEvents = function bindAdminPageEvents() {
        bindAdminEvents();
        resetAdminForm();
        loadAdminData(false);
    };

    function bindAdminEvents() {
        $(document).off('click.adminOpenForm', '#btn-open-admin-form');
        $(document).on('click.adminOpenForm', '#btn-open-admin-form', function () {
            resetAdminForm();
            $('#admin-form-card').removeClass('hidden');
            $('#admin-form-title').text('Add Admin');
        });

        $(document).off('click.adminCloseForm', '#btn-close-admin-form');
        $(document).on('click.adminCloseForm', '#btn-close-admin-form', function () {
            $('#admin-form-card').addClass('hidden');
        });

        $(document).off('click.adminResetForm', '#btn-reset-admin-form');
        $(document).on('click.adminResetForm', '#btn-reset-admin-form', function () {
            resetAdminForm();
        });

        $(document).off('submit.adminForm', '#admin-form');
        $(document).on('submit.adminForm', '#admin-form', function (e) {
            e.preventDefault();
            saveAdmin();
        });

        $(document).off('click.adminRefresh', '#btn-refresh-admin');
        $(document).on('click.adminRefresh', '#btn-refresh-admin', function () {
            currentPage = 1;
            loadAdminData(false);
        });

        $(document).off('change.adminFilter', '#admin-filter-status');
        $(document).on('change.adminFilter', '#admin-filter-status', function () {
            currentPage = 1;
            loadAdminData(false);
        });

        $(document).off('keyup.adminSearch', '#admin-search');
        $(document).on('keyup.adminSearch', '#admin-search', debounce(function () {
            currentPage = 1;
            loadAdminData(false);
        }, 400));

        $(document).off('click.adminPrev', '#btn-prev-admin-page');
        $(document).on('click.adminPrev', '#btn-prev-admin-page', function () {
            if (currentPage <= 1) return;
            currentPage--;
            loadAdminData(false);
        });

        $(document).off('click.adminNext', '#btn-next-admin-page');
        $(document).on('click.adminNext', '#btn-next-admin-page', function () {
            if (currentPage >= totalPage) return;
            currentPage++;
            loadAdminData(false);
        });

        $(document).off('click.adminEdit', '.btn-edit-admin');
        $(document).on('click.adminEdit', '.btn-edit-admin', function () {
            const id = Number($(this).data('id'));
            const row = adminRows.find(function (item) {
                return Number(item.id) === id;
            });

            if (!row) {
                showAlert('error', 'Not found', 'Admin data is not available.');
                return;
            }

            fillAdminForm(row);
        });

        $(document).off('click.adminDelete', '.btn-delete-admin');
        $(document).on('click.adminDelete', '.btn-delete-admin', function () {
            const id = Number($(this).data('id'));
            confirmDeleteAdmin(id);
        });
    }

    function loadAdminData(silent) {
        if (!silent) {
            $('#admin-table-body').html(`
                <tr>
                    <td colspan="5" class="px-6 py-8 text-center text-sm text-slate-400">
                        <i class="fa-solid fa-spinner fa-spin mr-2"></i>
                        Loading admins...
                    </td>
                </tr>
            `);
        }

        $.ajax({
            url: ADMIN_CRUD_URL,
            type: 'GET',
            dataType: 'json',
            data: {
                action: 'list',
                page: currentPage,
                limit: PAGE_SIZE,
                search: $('#admin-search').val() || '',
                status: $('#admin-filter-status').val() || ''
            },
            success: function (response) {
                if (!response || response.status !== true) {
                    renderAdminError(response && response.message ? response.message : 'Failed to load admins');
                    return;
                }

                adminRows = response.data || [];

                if (response.meta) {
                    currentPage = Number(response.meta.page || 1);
                    totalPage = Number(response.meta.total_page || 1);
                    totalRows = Number(response.meta.total || 0);
                } else {
                    totalPage = 1;
                    totalRows = adminRows.length;
                }

                if (totalPage < 1) totalPage = 1;
                if (currentPage < 1) currentPage = 1;
                if (currentPage > totalPage) currentPage = totalPage;

                renderAdminRows(adminRows);
                renderAdminPagination();
                updateAdminSummary();
            },
            error: function (xhr) {
                renderAdminError(getAjaxErrorMessage(xhr));
            }
        });
    }

    function saveAdmin() {
        const id = $('#admin-id').val();
        const action = id ? 'update' : 'create';

        const payload = {
            action: action,
            id: id,
            name: $('#admin-name').val(),
            email: $('#admin-email').val(),
            password: $('#admin-password').val(),
            role: $('#admin-role').val(),
            status: $('#admin-status').val()
        };

        $.ajax({
            url: ADMIN_CRUD_URL,
            type: 'POST',
            dataType: 'json',
            data: payload,
            success: function (response) {
                if (!response || response.status !== true) {
                    showAlert('error', 'Failed', response && response.message ? response.message : 'Failed to save admin');
                    return;
                }

                showAlert('success', 'Success', response.message);
                resetAdminForm();
                $('#admin-form-card').addClass('hidden');
                loadAdminData(false);
            },
            error: function (xhr) {
                showAlert('error', 'Failed', getAjaxErrorMessage(xhr));
            }
        });
    }

    function confirmDeleteAdmin(id) {
        if (!id) {
            showAlert('error', 'Invalid data', 'Invalid admin ID.');
            return;
        }

        Swal.fire({
            title: 'Delete admin?',
            text: 'This admin account will be permanently deleted.',
            icon: 'warning',
            showCancelButton: true,
            confirmButtonColor: '#e11d48',
            cancelButtonColor: '#64748b',
            confirmButtonText: 'Delete'
        }).then(function (result) {
            if (!result.isConfirmed) return;

            $.ajax({
                url: ADMIN_CRUD_URL,
                type: 'POST',
                dataType: 'json',
                data: {
                    action: 'delete',
                    id: id
                },
                success: function (response) {
                    if (!response || response.status !== true) {
                        showAlert('error', 'Failed', response && response.message ? response.message : 'Failed to delete admin');
                        return;
                    }

                    showAlert('success', 'Deleted', response.message);
                    loadAdminData(false);
                },
                error: function (xhr) {
                    showAlert('error', 'Failed', getAjaxErrorMessage(xhr));
                }
            });
        });
    }

    function renderAdminRows(rows) {
        const $tbody = $('#admin-table-body');
        $tbody.empty();

        if (!rows.length) {
            $tbody.html(`
                <tr>
                    <td colspan="5" class="px-6 py-8 text-center text-sm text-slate-400">
                        No admin data found.
                    </td>
                </tr>
            `);
            return;
        }

        rows.forEach(function (row) {
            $tbody.append(`
                <tr class="hover:bg-slate-50">
                    <td class="px-6 py-4">
                        <div class="font-semibold text-sm text-slate-800">${escapeHtml(row.name || '-')}</div>
                        <div class="text-xs text-slate-400 mt-1">${escapeHtml(row.email || '-')}</div>
                    </td>

                    <td class="px-6 py-4 text-sm text-slate-600">
                        ${escapeHtml(row.role || '-')}
                    </td>

                    <td class="px-6 py-4">
                        ${buildStatusBadge(row.status)}
                    </td>

                    <td class="px-6 py-4 text-sm text-slate-500">
                        ${escapeHtml(row.created_at || '-')}
                    </td>

                    <td class="px-6 py-4 text-right whitespace-nowrap">
                        <button type="button" class="btn-edit-admin text-slate-400 hover:text-indigo-600 p-1" data-id="${escapeHtml(row.id)}" title="Edit">
                            <i class="fa-regular fa-pen-to-square"></i>
                        </button>

                        <button type="button" class="btn-delete-admin text-slate-400 hover:text-rose-600 p-1" data-id="${escapeHtml(row.id)}" title="Delete">
                            <i class="fa-regular fa-trash-can"></i>
                        </button>
                    </td>
                </tr>
            `);
        });
    }

    function fillAdminForm(row) {
        $('#admin-form-title').text('Edit Admin');
        $('#admin-id').val(row.id || '');
        $('#admin-name').val(row.name || '');
        $('#admin-email').val(row.email || '');
        $('#admin-password').val('');
        $('#admin-role').val(row.role || 'ADMIN');
        $('#admin-status').val(row.status || 'ACTIVE');
        $('#admin-form-card').removeClass('hidden');
    }

    function resetAdminForm() {
        $('#admin-id').val('');
        $('#admin-name').val('');
        $('#admin-email').val('');
        $('#admin-password').val('');
        $('#admin-role').val('ADMIN');
        $('#admin-status').val('ACTIVE');
        $('#admin-form-title').text('Add Admin');
    }

    function renderAdminPagination() {
        $('#admin-page-info').text('Page ' + currentPage + ' / ' + totalPage);

        $('#btn-prev-admin-page')
            .prop('disabled', currentPage <= 1)
            .toggleClass('opacity-40 cursor-not-allowed', currentPage <= 1);

        $('#btn-next-admin-page')
            .prop('disabled', currentPage >= totalPage)
            .toggleClass('opacity-40 cursor-not-allowed', currentPage >= totalPage);
    }

    function updateAdminSummary() {
        const start = totalRows === 0 ? 0 : ((currentPage - 1) * PAGE_SIZE) + 1;
        const end = Math.min(currentPage * PAGE_SIZE, totalRows);

        $('#admin-list-summary').text('Showing ' + start + '-' + end + ' of ' + totalRows + ' admins');
    }

    function renderAdminError(message) {
        $('#admin-table-body').html(`
            <tr>
                <td colspan="5" class="px-6 py-8 text-center text-sm text-rose-500">
                    ${escapeHtml(message)}
                </td>
            </tr>
        `);
    }

    function buildStatusBadge(status) {
        if (status === 'ACTIVE') {
            return `
                <span class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-emerald-50 text-emerald-700">
                    Active
                </span>
            `;
        }

        return `
            <span class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-slate-100 text-slate-600">
                Inactive
            </span>
        `;
    }

    function getAjaxErrorMessage(xhr) {
        if (xhr && xhr.responseJSON && xhr.responseJSON.message) {
            return xhr.responseJSON.message;
        }

        if (xhr && xhr.responseText) {
            try {
                const parsed = JSON.parse(xhr.responseText);

                if (parsed.message) {
                    return parsed.message;
                }
            } catch (e) {
                return xhr.responseText.substring(0, 150);
            }
        }

        return 'Request failed';
    }

    function showAlert(icon, title, text) {
        if (window.Swal) {
            Swal.fire({
                icon: icon,
                title: title,
                text: text,
                confirmButtonColor: '#4f46e5'
            });
        } else {
            alert(title + '\n' + text);
        }
    }

    function debounce(callback, delay) {
        let timer = null;

        return function () {
            clearTimeout(timer);

            const args = arguments;
            const context = this;

            timer = setTimeout(function () {
                callback.apply(context, args);
            }, delay);
        };
    }

    function escapeHtml(value) {
        return String(value ?? '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    }

})(window, jQuery);