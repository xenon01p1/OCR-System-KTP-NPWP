// controllers/view-home.js

(function (window, $) {
    'use strict';

    const HOME_SUMMARY_URL = 'controllers/home-summary.php';

    window.bindHomePageEvents = function bindHomePageEvents() {
        bindHomeActions();
        loadHomeSummary(false);
    };

    function bindHomeActions() {
        $(document).off('click.homeRefresh', '#btn-refresh-home');
        $(document).on('click.homeRefresh', '#btn-refresh-home', function () {
            loadHomeSummary(false);
        });

        $(document).off('click.homeGoOcr', '#btn-go-ocr-page');
        $(document).on('click.homeGoOcr', '#btn-go-ocr-page', function () {
            $('#nav-ocr').trigger('click');
        });
    }

    function loadHomeSummary(silent) {
        if (!silent) {
            $('#home-latest-table-body').html(`
                <tr>
                    <td colspan="5" class="px-6 py-8 text-center text-sm text-slate-400">
                        <i class="fa-solid fa-spinner fa-spin mr-2"></i>
                        Loading dashboard data...
                    </td>
                </tr>
            `);
        }

        $.ajax({
            url: HOME_SUMMARY_URL,
            type: 'GET',
            dataType: 'json',
            success: function (response) {
                if (!response || response.status !== true) {
                    renderHomeError(response && response.message ? response.message : 'Failed to load dashboard');
                    return;
                }

                renderHomeSummary(response.data || {});
            },
            error: function (xhr) {
                renderHomeError(getAjaxErrorMessage(xhr));
            }
        });
    }

    function renderHomeSummary(data) {
        $('#home-total-files').text(formatNumber(data.total_files || 0));
        $('#home-success-rate').text((Number(data.success_rate || 0)).toFixed(2) + '%');
        $('#home-active-engine').text(data.latest_engine || '-');

        $('#home-pending-count').text(formatNumber(data.pending_count || 0));
        $('#home-processing-count').text(formatNumber(data.processing_count || 0));
        $('#home-success-count').text(formatNumber(data.success_count || 0));
        $('#home-failed-count').text(formatNumber(data.failed_count || 0));

        renderLatestUploads(data.latest_uploads || []);
    }

    function renderLatestUploads(rows) {
        const $tbody = $('#home-latest-table-body');
        $tbody.empty();

        if (!rows.length) {
            $tbody.html(`
                <tr>
                    <td colspan="5" class="px-6 py-8 text-center text-sm text-slate-400">
                        No upload data found.
                    </td>
                </tr>
            `);
            return;
        }

        rows.forEach(function (row) {
            $tbody.append(`
                <tr class="hover:bg-slate-50">
                    <td class="px-6 py-4">
                        <div class="font-semibold text-sm text-slate-800 break-words">
                            ${escapeHtml(row.original_filename || '-')}
                        </div>
                        <div class="text-xs text-slate-400 mt-1">
                            ID #${escapeHtml(row.id)}
                        </div>
                    </td>

                    <td class="px-6 py-4 text-sm text-slate-600">
                        ${escapeHtml(row.ocr_library || '-')}
                    </td>

                    <td class="px-6 py-4 text-sm text-slate-600">
                        ${escapeHtml(row.document_type || 'UNKNOWN')}
                    </td>

                    <td class="px-6 py-4">
                        ${buildStatusBadge(row.status)}
                    </td>

                    <td class="px-6 py-4 text-sm text-slate-500">
                        ${escapeHtml(row.created_at || '-')}
                    </td>
                </tr>
            `);
        });
    }

    function buildStatusBadge(status) {
        if (status === 'SUCCESS') {
            return `
                <span class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-emerald-50 text-emerald-700">
                    Success
                </span>
            `;
        }

        if (status === 'FAILED') {
            return `
                <span class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-rose-50 text-rose-700">
                    Failed
                </span>
            `;
        }

        if (status === 'PROCESSING') {
            return `
                <span class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-blue-50 text-blue-700">
                    Processing
                </span>
            `;
        }

        return `
            <span class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-amber-50 text-amber-700">
                Pending
            </span>
        `;
    }

    function renderHomeError(message) {
        $('#home-latest-table-body').html(`
            <tr>
                <td colspan="5" class="px-6 py-8 text-center text-sm text-rose-500">
                    ${escapeHtml(message)}
                </td>
            </tr>
        `);
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

    function formatNumber(value) {
        return Number(value || 0).toLocaleString('en-US');
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