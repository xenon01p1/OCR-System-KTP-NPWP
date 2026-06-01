// Place this file in your frontend controllers/ folder and load it after jQuery/SweetAlert.
// API base assumes Flask runs on http://127.0.0.1:8088.
const OCR_API_BASE = 'http://127.0.0.1:8088/api';

function bindOcrPageEvents() {
    const $form = $('#ocr-upload-form');
    const $fileInput = $('#file-input');

    $fileInput.off('change').on('change', function () {
        const files = Array.from(this.files || []);
        const $preview = $('#file-list-preview');
        const $container = $('#preview-container');
        $container.empty();

        if (!files.length) {
            $preview.addClass('hidden');
            return;
        }

        files.forEach(file => {
            $container.append(`
                <div class="text-xs bg-slate-100 rounded-lg px-3 py-2 flex justify-between">
                    <span>${file.name}</span>
                    <span>${(file.size / 1024 / 1024).toFixed(2)} MB</span>
                </div>
            `);
        });
        $preview.removeClass('hidden');
    });

    $form.off('submit').on('submit', function (e) {
        e.preventDefault();

        const files = $fileInput[0].files;
        if (!files || !files.length) {
            Swal.fire('Validation', 'Please select at least one file.', 'warning');
            return;
        }

        const formData = new FormData();
        formData.append('ocr_library', $('#ocr-library').val());
        Array.from(files).forEach(file => formData.append('files[]', file));

        $.ajax({
            url: `${OCR_API_BASE}/ocr/upload`,
            method: 'POST',
            data: formData,
            processData: false,
            contentType: false,
            beforeSend: function () {
                Swal.fire({
                    title: 'Uploading...',
                    text: 'OCR jobs are being queued.',
                    allowOutsideClick: false,
                    didOpen: () => Swal.showLoading()
                });
            },
            success: function (res) {
                Swal.fire('Success', res.message, 'success');
                $form[0].reset();
                $('#file-list-preview').addClass('hidden');
                loadOcrFiles();
            },
            error: function (xhr) {
                const msg = xhr.responseJSON?.message || 'Upload failed.';
                Swal.fire('Error', msg, 'error');
            }
        });
    });

    $('#tab-upload-btn').off('click').on('click', function () {
        $('#tab-upload').removeClass('hidden').addClass('active');
        $('#tab-data').addClass('hidden').removeClass('active');
        $('#tab-upload-btn').addClass('border-indigo-600 text-indigo-600').removeClass('border-transparent text-slate-400');
        $('#tab-data-btn').removeClass('border-indigo-600 text-indigo-600').addClass('border-transparent text-slate-400');
    });

    $('#tab-data-btn').off('click').on('click', function () {
        $('#tab-data').removeClass('hidden').addClass('active');
        $('#tab-upload').addClass('hidden').removeClass('active');
        $('#tab-data-btn').addClass('border-indigo-600 text-indigo-600').removeClass('border-transparent text-slate-400');
        $('#tab-upload-btn').removeClass('border-indigo-600 text-indigo-600').addClass('border-transparent text-slate-400');
        loadOcrFiles();
    });

    loadOcrFiles();
    setInterval(loadOcrFiles, 5000);
}

function statusBadge(status) {
    const map = {
        queued: 'bg-slate-50 text-slate-700',
        processing: 'bg-amber-50 text-amber-700',
        success: 'bg-emerald-50 text-emerald-700',
        failed: 'bg-rose-50 text-rose-700'
    };
    return `<span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${map[status] || map.queued}">${status}</span>`;
}

function loadOcrFiles() {
    $.get(`${OCR_API_BASE}/ocr/files`, function (res) {
        const rows = res.data || [];
        const $tbody = $('#data-table-body');
        if (!$tbody.length) return;
        $tbody.empty();

        if (!rows.length) {
            $tbody.append(`<tr><td colspan="5" class="px-6 py-4 text-center text-slate-400">No OCR data yet.</td></tr>`);
            return;
        }

        rows.forEach(row => {
            const engine = row.ocr_library || row.ocr_engine || 'hybrid-field-merge';
            const fileUrl = `http://127.0.0.1:8088/${row.filepath}`;
            const payload = row.json_payload || {};
            const score = payload.score || 0;
            const accuracy = score ? Math.min(score * 10, 100) : 0;

            $tbody.append(`
                <tr data-id="${row.id}">
                    <td class="px-6 py-4">
                        <span class="bg-indigo-50 text-indigo-700 px-2.5 py-1 rounded-md text-xs font-semibold">
                            ${engine}
                        </span>
                    </td>

                    <td class="px-6 py-4">
                        <a href="${fileUrl}" target="_blank" class="text-indigo-600 hover:underline font-semibold">
                            <i class="fa-regular fa-file mr-1.5"></i>${row.filename}
                        </a>
                    </td>

                    <td class="px-6 py-4">
                        <div class="flex items-center space-x-2 w-32">
                            <span class="font-semibold text-slate-900 text-xs">${accuracy}%</span>
                            <div class="w-full bg-slate-100 rounded-full h-1.5">
                                <div class="bg-indigo-600 h-1.5 rounded-full" style="width: ${accuracy}%"></div>
                            </div>
                        </div>
                    </td>

                    <td class="px-6 py-4">${statusBadge(row.status)}</td>

                    <td class="px-6 py-4 text-right space-x-2">
                        <button class="btn-detail text-slate-400 hover:text-indigo-600 p-1" data-id="${row.id}">
                            <i class="fa-regular fa-eye text-base"></i>
                        </button>
                        <button class="btn-delete text-slate-400 hover:text-rose-600 p-1" data-id="${row.id}">
                            <i class="fa-regular fa-trash-can text-base"></i>
                        </button>
                    </td>
                </tr>
            `);
        });

        $('.btn-detail').off('click').on('click', function () {
            showOcrDetail($(this).data('id'));
        });
        $('.btn-delete').off('click').on('click', function () {
            deleteOcrFile($(this).data('id'));
        });
    });
}

function showOcrDetail(id) {
    $.get(`${OCR_API_BASE}/ocr/files/${id}`, function (res) {
        const payload = res.data?.json_payload || {};
        Swal.fire({
            title: `OCR Detail`,
            html: `<pre style="text-align:left;max-height:420px;overflow:auto;font-size:12px;background:#f8fafc;padding:12px;border-radius:8px;">${JSON.stringify(payload, null, 2)}</pre>`,
            width: 900
        });
    });
}

function deleteOcrFile(id) {
    Swal.fire({
        title: 'Delete this OCR record?',
        icon: 'warning',
        showCancelButton: true,
        confirmButtonText: 'Delete'
    }).then(result => {
        if (!result.isConfirmed) return;
        $.ajax({
            url: `${OCR_API_BASE}/ocr/files/${id}`,
            method: 'DELETE',
            success: function () {
                Swal.fire('Deleted', 'OCR record deleted.', 'success');
                loadOcrFiles();
            }
        });
    });
}

// If your SPA calls custom view init after loading components/view-ocr.html, call bindOcrPageEvents() there.
$(document).ready(function () {
    if ($('#ocr-upload-form').length) bindOcrPageEvents();
});
