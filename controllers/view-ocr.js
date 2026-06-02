// controllers/view-ocr.js

(function (window, $) {
    'use strict';

    const UPLOAD_URL = 'controllers/ocr-upload.php';
    const LIST_URL = 'controllers/ocr-list.php';

    const PAGE_SIZE = 50;
    const DEFAULT_SCORE_MAX = 14;

    const DOCUMENT_SCORE_MAX = {
        KTP: 14,
        NPWP: 9
    };
    const MAX_FILE_SIZE = 10 * 1024 * 1024; // 10MB
    const ALLOWED_EXTENSIONS = ['jpg', 'jpeg', 'png', 'pdf'];

    const OCR_LIBRARY_OPTIONS = [
        { value: 'EasyOCR', label: 'EasyOCR' },
        { value: 'Tesseract OCR', label: 'Tesseract OCR (Open Source)' },
        { value: 'OpenCV Tesseract', label: 'OpenCV Tesseract' },
        { value: 'PaddleOCR', label: 'PaddleOCR (Multilingual)' }
    ];

    let ocrRows = [];
    let refreshTimer = null;
    let isLoadingData = false;

    let currentPage = 1;
    let totalPage = 1;
    let totalRows = 0;

    window.bindOcrPageEvents = function bindOcrPageEvents() {
        syncOcrLibraryOptions();
        ensureDataToolbar();
        ensureCompactTableLayout();
        bindUploadForm();
        bindDataEvents();
        loadOcrData(false);
        startAutoRefresh();
    };

    function syncOcrLibraryOptions() {
        const $select = $('#ocr-library');

        if (!$select.length) return;

        const currentValue = $select.val();

        $select.empty();

        OCR_LIBRARY_OPTIONS.forEach(function (item) {
            $select.append(
                $('<option>', {
                    value: item.value,
                    text: item.label
                })
            );
        });

        const exists = OCR_LIBRARY_OPTIONS.some(function (item) {
            return item.value === currentValue;
        });

        $select.val(exists ? currentValue : OCR_LIBRARY_OPTIONS[0].value);
    }

    function ensureDataToolbar() {
        if (!$('#tab-data').length || $('#ocr-data-toolbar').length) return;

        $('#tab-data').prepend(`
            <div id="ocr-data-toolbar" class="mb-4 flex items-center justify-between gap-2">
                <div>
                    <h2 class="text-sm font-semibold text-slate-800">OCR Upload Queue</h2>
                    <p id="ocr-data-summary" class="text-xs text-slate-400 mt-1">Loading data...</p>
                </div>

                <div class="flex items-center gap-2">
                    <button id="btn-prev-ocr-page" type="button" class="bg-white border border-slate-200 hover:border-indigo-500 text-slate-600 hover:text-indigo-600 text-xs font-semibold px-3 py-2 rounded-lg transition-all">
                        Prev
                    </button>

                    <span id="ocr-page-info" class="text-xs text-slate-500 min-w-[90px] text-center">
                        Page 1 / 1
                    </span>

                    <button id="btn-next-ocr-page" type="button" class="bg-white border border-slate-200 hover:border-indigo-500 text-slate-600 hover:text-indigo-600 text-xs font-semibold px-3 py-2 rounded-lg transition-all">
                        Next
                    </button>

                    <button id="btn-refresh-ocr-data" type="button" class="bg-white border border-slate-200 hover:border-indigo-500 text-slate-600 hover:text-indigo-600 text-xs font-semibold px-3 py-2 rounded-lg transition-all">
                        <i class="fa-solid fa-rotate-right mr-1"></i>
                        Refresh
                    </button>
                </div>
            </div>
        `);
    }

    function ensureCompactTableLayout() {
        const $table = $('#data-table-body').closest('table');

        if (!$table.length) return;

        $table.addClass('table-fixed');

        if (!$table.find('colgroup').length) {
            $table.prepend(`
                <colgroup>
                    <col style="width: 20%;">
                    <col style="width: 32%;">
                    <col style="width: 15%;">
                    <col style="width: 17%;">
                    <col style="width: 16%;">
                </colgroup>
            `);
        }

        $('#tab-data thead th')
            .removeClass('px-6 py-4')
            .addClass('px-4 py-3');
    }

    function bindUploadForm() {
        $(document).off('submit.ocrUpload', '#ocr-upload-form');

        $(document).on('submit.ocrUpload', '#ocr-upload-form', async function (e) {
            e.preventDefault();

            const fileInput = document.getElementById('file-input');
            const files = fileInput && fileInput.files ? Array.from(fileInput.files) : [];
            const ocrLibrary = $('#ocr-library').val();

            if (!ocrLibrary) {
                showAlert('warning', 'OCR library required', 'Please select OCR library first.');
                return;
            }

            if (!files.length) {
                showAlert('warning', 'No file selected', 'Please select at least one document.');
                return;
            }

            const isLibraryAllowed = OCR_LIBRARY_OPTIONS.some(function (item) {
                return item.value === ocrLibrary;
            });

            if (!isLibraryAllowed) {
                showAlert('error', 'Invalid OCR library', 'Selected OCR library is not supported by frontend.');
                return;
            }

            const $button = $('#ocr-upload-form button[type="submit"]');
            const originalButtonHtml = $button.html();

            $button
                .prop('disabled', true)
                .addClass('opacity-70 cursor-not-allowed')
                .html('<i class="fa-solid fa-spinner fa-spin"></i><span> Uploading...</span>');

            let queuedCount = 0;
            let failedCount = 0;

            $('#tab-data-btn').trigger('click');

            for (const file of files) {
                const validation = validateFile(file);

                if (!validation.valid) {
                    failedCount++;

                    addTemporaryUploadRow({
                        fileName: file.name,
                        fileSize: file.size,
                        ocrLibrary: ocrLibrary,
                        status: 'FAILED',
                        message: validation.message
                    });

                    continue;
                }

                try {
                    addTemporaryUploadRow({
                        fileName: file.name,
                        fileSize: file.size,
                        ocrLibrary: ocrLibrary,
                        status: 'UPLOADING',
                        message: 'Uploading...'
                    });

                    const response = await uploadSingleFile(file, ocrLibrary);
                    const uploadedItem = getFirstUploadedItem(response);

                    if (response && response.status === true && uploadedItem && uploadedItem.status === true) {
                        queuedCount++;
                    } else {
                        failedCount++;
                    }
                } catch (xhr) {
                    failedCount++;
                    console.error(getAjaxErrorMessage(xhr));
                }
            }

            $button
                .prop('disabled', false)
                .removeClass('opacity-70 cursor-not-allowed')
                .html(originalButtonHtml);

            $('#file-input').val('');
            $('#preview-container').empty();
            $('#file-list-preview').addClass('hidden');

            currentPage = 1;
            loadOcrData(false);

            if (failedCount === 0) {
                showAlert(
                    'success',
                    'Upload queued',
                    queuedCount + ' file(s) inserted into database. Python worker will process them.'
                );
            } else {
                showAlert(
                    'warning',
                    'Upload completed with errors',
                    queuedCount + ' file(s) queued, ' + failedCount + ' file(s) failed.'
                );
            }
        });
    }

    function bindDataEvents() {
        $(document).off('click.ocrRefresh', '#btn-refresh-ocr-data');
        $(document).on('click.ocrRefresh', '#btn-refresh-ocr-data', function () {
            currentPage = 1;
            loadOcrData(false);
        });

        $(document).off('click.ocrPrevPage', '#btn-prev-ocr-page');
        $(document).on('click.ocrPrevPage', '#btn-prev-ocr-page', function () {
            if (currentPage <= 1) return;

            currentPage--;
            loadOcrData(false);
        });

        $(document).off('click.ocrNextPage', '#btn-next-ocr-page');
        $(document).on('click.ocrNextPage', '#btn-next-ocr-page', function () {
            if (currentPage >= totalPage) return;

            currentPage++;
            loadOcrData(false);
        });

        $(document).off('click.ocrDetail', '.btn-ocr-detail');
        $(document).on('click.ocrDetail', '.btn-ocr-detail', function () {
            const id = Number($(this).data('id'));

            const row = ocrRows.find(function (item) {
                return Number(item.id) === id;
            });

            if (!row) {
                showAlert('error', 'Data not found', 'Selected OCR data is not available.');
                return;
            }

            showDetailModal(row);
        });
    }

    function startAutoRefresh() {
        if (refreshTimer) {
            clearInterval(refreshTimer);
        }

        refreshTimer = setInterval(function () {
            if (!$('#data-table-body').length) {
                clearInterval(refreshTimer);
                refreshTimer = null;
                return;
            }

            loadOcrData(true);
        }, 5000);
    }

    function uploadSingleFile(file, ocrLibrary) {
        const formData = new FormData();

        formData.append('ocr_library', ocrLibrary);
        formData.append('documents[]', file, file.name);

        return $.ajax({
            url: UPLOAD_URL,
            type: 'POST',
            data: formData,
            dataType: 'json',
            processData: false,
            contentType: false,
            timeout: 120000
        });
    }

    function loadOcrData(silent) {
        if (!$('#data-table-body').length || isLoadingData) return;

        isLoadingData = true;

        if (!silent) {
            $('#data-table-body').html(`
                <tr>
                    <td colspan="5" class="px-4 py-8 text-center text-sm text-slate-400">
                        <i class="fa-solid fa-spinner fa-spin mr-2"></i>
                        Loading OCR data...
                    </td>
                </tr>
            `);
        }

        $.ajax({
            url: LIST_URL,
            type: 'GET',
            dataType: 'json',
            data: {
                page: currentPage,
                limit: PAGE_SIZE
            },
            success: function (response) {
                if (!response || response.status !== true) {
                    renderErrorRow(response && response.message ? response.message : 'Failed to load data');
                    return;
                }

                ocrRows = response.data || [];

                if (response.meta) {
                    currentPage = Number(response.meta.page || 1);
                    totalPage = Number(response.meta.total_page || 1);
                    totalRows = Number(response.meta.total || 0);
                } else {
                    totalPage = 1;
                    totalRows = ocrRows.length;
                }

                if (totalPage < 1) totalPage = 1;
                if (currentPage < 1) currentPage = 1;
                if (currentPage > totalPage) currentPage = totalPage;

                renderPagination();
                renderOcrRows(ocrRows);
                updateSummary(response.meta);
            },
            error: function (xhr) {
                renderErrorRow(getAjaxErrorMessage(xhr));
            },
            complete: function () {
                isLoadingData = false;
            }
        });
    }

    function renderPagination() {
        if (!$('#ocr-page-info').length) return;

        if (totalPage < 1) {
            totalPage = 1;
        }

        $('#ocr-page-info').text('Page ' + currentPage + ' / ' + totalPage);

        $('#btn-prev-ocr-page')
            .prop('disabled', currentPage <= 1)
            .toggleClass('opacity-40 cursor-not-allowed', currentPage <= 1);

        $('#btn-next-ocr-page')
            .prop('disabled', currentPage >= totalPage)
            .toggleClass('opacity-40 cursor-not-allowed', currentPage >= totalPage);
    }

    function renderOcrRows(rows) {
        const $tbody = $('#data-table-body');
        $tbody.empty();

        if (!rows.length) {
            $tbody.html(`
                <tr>
                    <td colspan="5" class="px-4 py-8 text-center text-sm text-slate-400">
                        No OCR upload data found.
                    </td>
                </tr>
            `);
            return;
        }

        rows.forEach(function (row) {
            $tbody.append(buildRowHtml(row));
        });
    }

    function buildRowHtml(row) {
        const fileIcon = getFileExtension(row.original_filename) === 'pdf'
            ? 'fa-regular fa-file-pdf'
            : 'fa-regular fa-file-image';

        const accuracyHtml = buildAccuracyHtml(row);
        const statusHtml = buildStatusBadge(row.status, row.error_message);
        const fileUrl = row.file_url || row.filepath || '#';

        return `
            <tr>
                <td class="px-4 py-3 align-top">
                    <span class="bg-indigo-50 text-indigo-700 px-2 py-1 rounded-md text-xs font-semibold break-words inline-block max-w-full">
                        ${escapeHtml(row.ocr_library || '-')}
                    </span>
                    <div class="text-xs text-slate-400 mt-1">
                        ${escapeHtml(row.document_type || 'UNKNOWN')}
                    </div>
                </td>

                <td class="px-4 py-3 align-top">
                    <a href="${escapeHtml(fileUrl)}" target="_blank" class="text-indigo-600 hover:underline font-semibold break-words">
                        <i class="${fileIcon} mr-1"></i>${escapeHtml(row.original_filename || '-')}
                    </a>
                    <div class="text-xs text-slate-400 mt-1">
                        ID #${escapeHtml(row.id)} · ${escapeHtml(row.created_at || '-')}
                    </div>
                </td>

                <td class="px-4 py-3 align-top">
                    ${accuracyHtml}
                </td>

                <td class="px-4 py-3 align-top">
                    ${statusHtml}
                </td>

                <td class="px-4 py-3 align-top text-right whitespace-nowrap">
                    <button type="button" class="btn-ocr-detail text-slate-400 hover:text-indigo-600 p-1" data-id="${escapeHtml(row.id)}" title="View detail">
                        <i class="fa-regular fa-eye text-base"></i>
                    </button>

                    <a href="${escapeHtml(fileUrl)}" target="_blank" class="text-slate-400 hover:text-indigo-600 p-1 inline-block" title="Open file">
                        <i class="fa-solid fa-arrow-up-right-from-square text-sm"></i>
                    </a>
                </td>
            </tr>
        `;
    }

    function addTemporaryUploadRow(data) {
        const $tbody = $('#data-table-body');

        if (!$tbody.length) return;

        if ($tbody.find('td[colspan="5"]').length) {
            $tbody.empty();
        }

        const fileIcon = getFileExtension(data.fileName) === 'pdf'
            ? 'fa-regular fa-file-pdf'
            : 'fa-regular fa-file-image';

        const statusHtml = data.status === 'FAILED'
            ? buildStatusBadge('FAILED', data.message)
            : buildStatusBadge('PROCESSING', data.message);

        const accuracyText = data.status === 'FAILED'
            ? '<span class="text-xs text-rose-600 font-semibold">Failed</span>'
            : '<span class="text-xs text-blue-600 font-semibold">Uploading</span>';

        $tbody.prepend(`
            <tr class="bg-slate-50">
                <td class="px-4 py-3 align-top">
                    <span class="bg-indigo-50 text-indigo-700 px-2 py-1 rounded-md text-xs font-semibold break-words inline-block max-w-full">
                        ${escapeHtml(data.ocrLibrary || '-')}
                    </span>
                    <div class="text-xs text-slate-400 mt-1">LOCAL</div>
                </td>

                <td class="px-4 py-3 align-top">
                    <span class="text-slate-800 font-semibold break-words">
                        <i class="${fileIcon} mr-1"></i>${escapeHtml(data.fileName || '-')}
                    </span>
                    <div class="text-xs text-slate-400 mt-1">${formatBytes(data.fileSize)}</div>
                </td>

                <td class="px-4 py-3 align-top">${accuracyText}</td>
                <td class="px-4 py-3 align-top">${statusHtml}</td>
                <td class="px-4 py-3 align-top text-right whitespace-nowrap">
                    <span class="text-xs text-slate-400">Temporary</span>
                </td>
            </tr>
        `);
    }

    function buildAccuracyHtml(row) {
        if (row.status === 'PENDING') {
            return '<span class="text-xs text-amber-600 font-semibold">Waiting worker</span>';
        }

        if (row.status === 'PROCESSING') {
            return '<span class="text-xs text-blue-600 font-semibold">Processing</span>';
        }

        if (row.status === 'FAILED') {
            return '<span class="text-xs text-rose-600 font-semibold">Failed</span>';
        }

        const scoreInfo = getScoreInfo(row);

        if (scoreInfo.score === null || scoreInfo.percent === null) {
            return '<span class="text-xs text-slate-400">No score</span>';
        }

        return `
            <div class="w-36">
                <div class="flex items-center justify-between mb-1">
                    <span class="font-semibold text-slate-900 text-xs">${scoreInfo.percentText}%</span>
                    <span class="text-xs text-slate-400">${scoreInfo.score} / ${scoreInfo.scoreMax}</span>
                </div>

                <div class="w-full bg-slate-100 rounded-full h-1.5">
                    <div class="bg-indigo-600 h-1.5 rounded-full" style="width: ${scoreInfo.percentText}%"></div>
                </div>
            </div>
        `;
    }

    function buildStatusBadge(status, errorMessage) {
        if (status === 'SUCCESS') {
            return `
                <span class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-emerald-50 text-emerald-700">
                    <span class="w-1.5 h-1.5 bg-emerald-500 rounded-full mr-1.5"></span>
                    Success
                </span>
            `;
        }

        if (status === 'FAILED') {
            return `
                <span class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-rose-50 text-rose-700">
                    <span class="w-1.5 h-1.5 bg-rose-500 rounded-full mr-1.5"></span>
                    Failed
                </span>
                ${errorMessage ? `<div class="text-xs text-rose-500 mt-1 break-words">${escapeHtml(errorMessage)}</div>` : ''}
            `;
        }

        if (status === 'PROCESSING') {
            return `
                <span class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-blue-50 text-blue-700">
                    <span class="w-1.5 h-1.5 bg-blue-500 rounded-full mr-1.5"></span>
                    Processing
                </span>
                ${errorMessage ? `<div class="text-xs text-slate-400 mt-1 break-words">${escapeHtml(errorMessage)}</div>` : ''}
            `;
        }

        return `
            <span class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-amber-50 text-amber-700">
                <span class="w-1.5 h-1.5 bg-amber-500 rounded-full mr-1.5"></span>
                Pending
            </span>
            ${errorMessage ? `<div class="text-xs text-slate-400 mt-1 break-words">${escapeHtml(errorMessage)}</div>` : ''}
        `;
    }

    function showDetailModal(row) {
        const payload = getPayload(row);
        const fields = payload.fields || {};
        const rawText = payload.raw_text || '';
        const reviewReasons = Array.isArray(payload.review_reasons) ? payload.review_reasons : [];
        const scoreInfo = getScoreInfo(row);

        let fieldRows = '';

        Object.keys(fields).forEach(function (key) {
            fieldRows += `
                <tr>
                    <td class="px-3 py-2 text-xs font-semibold text-slate-500 border-b">${escapeHtml(key)}</td>
                    <td class="px-3 py-2 text-xs text-slate-700 border-b">${escapeHtml(fields[key] ?? '-')}</td>
                </tr>
            `;
        });

        if (!fieldRows) {
            fieldRows = `
                <tr>
                    <td colspan="2" class="px-3 py-4 text-xs text-slate-400 text-center">No extracted fields.</td>
                </tr>
            `;
        }

        const reviewHtml = reviewReasons.length
            ? `
                <div class="mt-4 bg-amber-50 text-amber-700 text-xs rounded-lg p-3">
                    <div class="font-semibold mb-1">Review Reasons</div>
                    <ul class="list-disc pl-4">
                        ${reviewReasons.map(function (reason) {
                            return `<li>${escapeHtml(reason)}</li>`;
                        }).join('')}
                    </ul>
                </div>
            `
            : '';

        Swal.fire({
            title: 'OCR Detail',
            width: 900,
            html: `
                <div class="text-left space-y-4">
                    <div class="grid grid-cols-2 gap-3 text-xs">
                        <div><b>File:</b> ${escapeHtml(row.original_filename || '-')}</div>
                        <div><b>Status:</b> ${escapeHtml(row.status || '-')}</div>
                        <div><b>Library:</b> ${escapeHtml(row.ocr_library || '-')}</div>
                        <div><b>Document:</b> ${escapeHtml(row.document_type || '-')}</div>
                        <div><b>Score:</b> ${escapeHtml(scoreInfo.score ?? '-')} / ${escapeHtml(scoreInfo.scoreMax || '-')}</div>
                        <div><b>Accuracy:</b> ${escapeHtml(scoreInfo.percentText || '-')}%</div>
                    </div>

                    ${reviewHtml}

                    <div>
                        <div class="text-xs font-semibold text-slate-600 mb-2">Extracted Fields</div>
                        <div class="border border-slate-200 rounded-lg overflow-hidden max-h-64 overflow-y-auto">
                            <table class="w-full border-collapse">
                                <tbody>${fieldRows}</tbody>
                            </table>
                        </div>
                    </div>

                    <div>
                        <div class="text-xs font-semibold text-slate-600 mb-2">Raw Text</div>
                        <pre class="bg-slate-50 border border-slate-200 rounded-lg p-3 text-xs text-slate-600 whitespace-pre-wrap max-h-64 overflow-y-auto">${escapeHtml(rawText || '-')}</pre>
                    </div>
                </div>
            `,
            confirmButtonColor: '#4f46e5'
        });
    }

    function getScoreInfo(row) {
        const payload = getPayload(row);
        const documentType = String(row.document_type || payload.document_type || 'UNKNOWN').toUpperCase();

        const rawScore = firstFiniteNumber(row.score, payload.score);

        let scoreMax = firstFiniteNumber(
            row.score_max,
            row.scoreMax,
            payload.score_max,
            payload.scoreMax,
            DOCUMENT_SCORE_MAX[documentType],
            DEFAULT_SCORE_MAX
        );

        if (!Number.isFinite(scoreMax) || scoreMax <= 0) {
            scoreMax = DEFAULT_SCORE_MAX;
        }

        if (!Number.isFinite(rawScore)) {
            return {
                score: null,
                scoreMax: scoreMax,
                percent: null,
                percentText: null
            };
        }

        const safeScore = Math.max(0, Math.min(scoreMax, rawScore));

        let percent = firstFiniteNumber(
            row.score_percent,
            row.scorePercent,
            payload.score_percent,
            payload.scorePercent
        );

        if (!Number.isFinite(percent)) {
            percent = (safeScore / scoreMax) * 100;
        }

        percent = Math.max(0, Math.min(100, percent));

        return {
            score: formatScoreNumber(safeScore),
            scoreMax: formatScoreNumber(scoreMax),
            percent: percent,
            percentText: percent.toFixed(2)
        };
    }

    function getPayload(row) {
        if (!row || !row.json_payload) return {};

        if (typeof row.json_payload === 'object') {
            return row.json_payload;
        }

        if (typeof row.json_payload === 'string') {
            try {
                return JSON.parse(row.json_payload);
            } catch (e) {
                return {};
            }
        }

        return {};
    }

    function firstFiniteNumber() {
        for (let i = 0; i < arguments.length; i++) {
            const value = Number(arguments[i]);

            if (Number.isFinite(value)) {
                return value;
            }
        }

        return NaN;
    }

    function formatScoreNumber(value) {
        if (!Number.isFinite(value)) return value;

        return Number.isInteger(value) ? value : Number(value.toFixed(2));
    }

    function updateSummary(meta) {
        if (!$('#ocr-data-summary').length) return;

        const total = meta && meta.total !== undefined ? Number(meta.total) : totalRows;
        const start = total === 0 ? 0 : ((currentPage - 1) * PAGE_SIZE) + 1;
        const end = Math.min(currentPage * PAGE_SIZE, total);

        const pending = ocrRows.filter(function (row) {
            return row.status === 'PENDING';
        }).length;

        const processing = ocrRows.filter(function (row) {
            return row.status === 'PROCESSING';
        }).length;

        const success = ocrRows.filter(function (row) {
            return row.status === 'SUCCESS';
        }).length;

        const failed = ocrRows.filter(function (row) {
            return row.status === 'FAILED';
        }).length;

        $('#ocr-data-summary').text(
            'Showing ' + start + '-' + end + ' of ' + total +
            ' · Pending: ' + pending +
            ' · Processing: ' + processing +
            ' · Success: ' + success +
            ' · Failed: ' + failed
        );
    }

    function renderErrorRow(message) {
        $('#data-table-body').html(`
            <tr>
                <td colspan="5" class="px-4 py-8 text-center text-sm text-rose-500">
                    ${escapeHtml(message)}
                </td>
            </tr>
        `);
    }

    function validateFile(file) {
        const extension = getFileExtension(file.name);

        if (!ALLOWED_EXTENSIONS.includes(extension)) {
            return {
                valid: false,
                message: 'Invalid file type'
            };
        }

        if (file.size > MAX_FILE_SIZE) {
            return {
                valid: false,
                message: 'File too large. Max 10MB'
            };
        }

        return {
            valid: true,
            message: 'OK'
        };
    }

    function getFirstUploadedItem(response) {
        if (!response || !Array.isArray(response.data) || response.data.length === 0) {
            return null;
        }

        return response.data[0];
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

    function getFileExtension(filename) {
        return String(filename || '').split('.').pop().toLowerCase();
    }

    function formatBytes(bytes) {
        if (!bytes && bytes !== 0) return '-';

        if (bytes < 1024) {
            return bytes + ' B';
        }

        if (bytes < 1024 * 1024) {
            return (bytes / 1024).toFixed(1) + ' KB';
        }

        return (bytes / (1024 * 1024)).toFixed(2) + ' MB';
    }

    function escapeHtml(value) {
        return String(value ?? '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
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

})(window, jQuery);