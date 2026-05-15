/**
 * CloudProtect AI - Files Management Logic
 * Handles file previews, folder renaming, and live searching.
 */

function toggleVersions(id, btn) {
    const row = document.getElementById(id);
    if (!row) return;
    const isHidden = row.classList.contains('d-none');
    row.classList.toggle('d-none', !isHidden);
    btn.classList.toggle('active', isHidden);
    btn.innerHTML = isHidden ? '<i class="bi bi-chevron-up"></i> Hide' : '<i class="bi bi-layers-fill"></i> History';
}

function filterFiles() {
    const searchInput = document.getElementById('searchInput');
    if (!searchInput) return;
    const q = searchInput.value.toLowerCase().trim();
    const rows = document.querySelectorAll('#filesBody > tr:not([id])');
    
    rows.forEach(row => {
        const name = row.getAttribute('data-name') || '';
        const show = name.includes(q);
        row.style.display = show ? '' : 'none';
        if (!show) {
            const vrow = row.nextElementSibling;
            if (vrow && vrow.id && vrow.id.startsWith('vrow-')) {
                vrow.classList.add('d-none');
            }
        }
    });
}

function openRenameModal(id, name) {
    const form = document.getElementById('renameFolderForm');
    const input = document.getElementById('renameFolderName');
    const modalEl = document.getElementById('renameFolderModal');
    if (!form || !input || !modalEl) return;
    
    form.action = `/rename_folder/${id}`;
    input.value = name;
    const modal = new bootstrap.Modal(modalEl);
    modal.show();
}

function openPreview(fileId, fileName) {
    const modalEl = document.getElementById('previewModal');
    if (!modalEl) return;
    
    const modal = new bootstrap.Modal(modalEl);
    const container = document.getElementById('previewContent');
    const loading = document.getElementById('previewLoading');
    const title = document.getElementById('previewTitle');
    const meta = document.getElementById('previewMeta');
    const dlBtn = document.getElementById('previewDownloadBtn');
    
    if (!container || !loading || !title || !meta || !dlBtn) return;

    title.innerText = fileName;
    meta.innerText = "Initializing preview...";
    container.innerHTML = '';
    loading.classList.remove('d-none');
    dlBtn.href = `/download/${fileId}`;
    
    modal.show();
    
    const ext = fileName.split('.').pop().toLowerCase();
    const previewUrl = `/preview/${fileId}`;
    
    // Images
    if (['jpg', 'jpeg', 'png', 'gif', 'webp', 'svg'].includes(ext)) {
        const img = document.createElement('img');
        img.className = 'preview-content-img';
        img.src = previewUrl;
        img.alt = fileName;
        img.onload = () => {
            loading.classList.add('d-none');
            meta.innerText = "Image Preview";
        };
        img.onerror = () => {
            loading.classList.add('d-none');
            meta.innerText = "Error loading image";
        };
        container.appendChild(img);
    } 
    // Video
    else if (['mp4', 'webm', 'ogg'].includes(ext)) {
        const video = document.createElement('video');
        video.className = 'preview-content-video';
        video.controls = true;
        video.autoplay = true;
        const source = document.createElement('source');
        source.src = previewUrl;
        source.type = `video/${ext === 'mp4' ? 'mp4' : ext}`;
        video.appendChild(source);
        video.onloadeddata = () => {
            loading.classList.add('d-none');
            meta.innerText = "Video Preview";
        };
        container.appendChild(video);
    }
    // PDF
    else if (ext === 'pdf') {
        const iframe = document.createElement('iframe');
        iframe.className = 'preview-content-pdf';
        iframe.src = previewUrl;
        iframe.title = "PDF Preview";
        iframe.onload = () => {
            loading.classList.add('d-none');
            meta.innerText = "PDF Document";
        };
        container.appendChild(iframe);
    }
    // Text / Code
    else if (['txt', 'py', 'js', 'html', 'css', 'json', 'md', 'sql'].includes(ext)) {
        fetch(previewUrl)
            .then(res => res.text())
            .then(text => {
                const pre = document.createElement('pre');
                pre.className = 'preview-content-text';
                pre.innerText = text;
                container.appendChild(pre);
                loading.classList.add('d-none');
                meta.innerText = `${ext.toUpperCase()} Source File`;
            })
            .catch(err => {
                container.innerHTML = `<div class="preview-unsupported"><i class="bi bi-exclamation-triangle"></i><p>Failed to load text content.</p></div>`;
                loading.classList.add('d-none');
            });
    }
    // Unsupported
    else {
        loading.classList.add('d-none');
        container.innerHTML = `
            <div class="preview-unsupported">
                <i class="bi bi-file-earmark-lock2"></i>
                <p class="text-white fw-bold">Preview not available for this file type</p>
                <p class="text-muted small">Please download the file to view its contents.</p>
            </div>
        `;
        meta.innerText = "No Preview Available";
    }
}

// Close modal on ESC key
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
        const modalEl = document.getElementById('previewModal');
        if (modalEl) {
            const modal = bootstrap.Modal.getInstance(modalEl);
            if (modal) modal.hide();
        }
    }
});
// Dynamic Icon Mapping
document.addEventListener('DOMContentLoaded', () => {
    const dynamicIcons = document.querySelectorAll('.file-icon-dynamic');
    dynamicIcons.forEach(iconBox => {
        const filename = iconBox.getAttribute('data-filename');
        if (!filename) return;
        const ext = filename.split('.').pop().toLowerCase();
        const icon = iconBox.querySelector('i');
        if (!icon) return;

        // Reset class
        icon.className = 'bi';

        if (['jpg', 'jpeg', 'png', 'gif', 'webp', 'svg'].includes(ext)) {
            icon.classList.add('bi-file-earmark-image-fill', 'text-info');
        } else if (['mp4', 'webm', 'ogg', 'mov'].includes(ext)) {
            icon.classList.add('bi-file-earmark-play-fill', 'text-warning');
        } else if (['pdf'].includes(ext)) {
            icon.classList.add('bi-file-earmark-pdf-fill', 'text-danger');
        } else if (['zip', 'rar', '7z', 'tar', 'gz'].includes(ext)) {
            icon.classList.add('bi-file-earmark-zip-fill', 'text-warning');
        } else if (['py', 'js', 'html', 'css', 'json', 'md', 'sql', 'cpp', 'java'].includes(ext)) {
            icon.classList.add('bi-file-earmark-code-fill', 'text-success');
        } else if (['doc', 'docx', 'odt'].includes(ext)) {
            icon.classList.add('bi-file-earmark-word-fill', 'text-primary');
        } else if (['xls', 'xlsx', 'csv'].includes(ext)) {
            icon.classList.add('bi-file-earmark-excel-fill', 'text-success');
        } else {
            icon.classList.add('bi-file-earmark-fill', 'text-muted');
        }
    });
});
