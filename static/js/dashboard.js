/**
 * CloudProtect AI - Dashboard Logic
 * Handles file uploads, drag-and-drop, and AI Chatbot interactions.
 */

document.addEventListener('DOMContentLoaded', () => {
    // ── Upload Logic ──
    const dropZone = document.getElementById('dropZone');
    const fileInput = document.getElementById('fileInput');
    const progressWrap = document.getElementById('progressWrap');
    const progressFill = document.getElementById('progressFill');
    const uploadPct = document.getElementById('uploadPct');
    const uploadFName = document.getElementById('uploadFilename');
    const progStatus = document.getElementById('progressStatus');
    const folderSelect = document.getElementById('folderSelect');

    if (dropZone) {
        ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
            dropZone.addEventListener(eventName, e => { e.preventDefault(); e.stopPropagation(); });
        });

        ['dragenter', 'dragover'].forEach(eventName => {
            dropZone.addEventListener(eventName, () => dropZone.classList.add('dragover'));
        });
        ['dragleave', 'drop'].forEach(eventName => {
            dropZone.addEventListener(eventName, () => dropZone.classList.remove('dragover'));
        });

        dropZone.addEventListener('drop', e => {
            if (e.dataTransfer.files.length) uploadFile(e.dataTransfer.files[0]);
        });
        dropZone.addEventListener('click', () => fileInput.click());
    }

    if (fileInput) {
        fileInput.addEventListener('change', () => {
            if (fileInput.files.length) uploadFile(fileInput.files[0]);
        });
    }

    function uploadFile(file) {
        if (!progressWrap) return;
        
        progressWrap.classList.remove('d-none');
        uploadFName.textContent = file.name;
        uploadPct.textContent = '0%';
        progressFill.style.width = '0%';
        progStatus.textContent = 'Uploading...';
        progStatus.className = 'small mt-2 text-center text-muted';

        let formData = new FormData();
        formData.append('file', file);
        formData.append('folder_id', folderSelect ? folderSelect.value : '');

        let xhr = new XMLHttpRequest();
        // The upload URL is usually just /upload
        xhr.open('POST', '/upload', true);

        xhr.upload.addEventListener('progress', e => {
            if (e.lengthComputable) {
                let percent = Math.round((e.loaded / e.total) * 100);
                progressFill.style.width = percent + '%';
                uploadPct.textContent = percent + '%';
            }
        });

        xhr.onload = () => {
            let data = {};
            try { data = JSON.parse(xhr.responseText); } catch(e) {}
            
            if (xhr.status === 200 && data.success) {
                progStatus.textContent = 'Successfully uploaded!';
                progStatus.classList.replace('text-muted', 'text-success');
                setTimeout(() => location.reload(), 1500);
            } else {
                progStatus.textContent = data.error || 'Upload failed.';
                progStatus.classList.replace('text-muted', 'text-danger');
            }
        };

        xhr.onerror = () => {
            progStatus.textContent = 'Network error.';
            progStatus.classList.replace('text-muted', 'text-danger');
        };

        xhr.send(formData);
    }

    // ── AI Chatbot Logic ──
    const sidebar = document.getElementById('aiSidebar');
    const toggleBtn = document.getElementById('aiToggleBtn');
    const closeBtn = document.getElementById('closeAiBtn');
    const chatContainer = document.getElementById('chatContainer');
    const chatInput = document.getElementById('chatInput');
    const sendBtn = document.getElementById('sendBtn');
    const suggestionPills = document.querySelectorAll('.suggestion-pill');

    if (toggleBtn) {
        toggleBtn.addEventListener('click', toggleSidebar);
    }
    if (closeBtn) {
        closeBtn.addEventListener('click', toggleSidebar);
    }

    function toggleSidebar() {
        if (!sidebar) return;
        sidebar.classList.toggle('open');
        if (sidebar.classList.contains('open') && chatInput) chatInput.focus();
    }

    function appendMessage(text, sender) {
        if (!chatContainer) return;
        const div = document.createElement('div');
        div.className = `chat-bubble-premium chat-${sender}-premium`;
        // Basic markdown-like bold and line breaks
        div.innerHTML = text.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>').replace(/\n/g, '<br>');
        chatContainer.appendChild(div);
        chatContainer.scrollTop = chatContainer.scrollHeight;
    }

    async function sendMessage(text) {
        if (!text || !text.trim()) return;
        appendMessage(text, 'user');
        if (chatInput) chatInput.value = '';
        
        // Typing indicator
        const typing = document.createElement('div');
        typing.className = 'chat-bubble-premium chat-ai-premium small opacity-50';
        typing.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Thinking...';
        chatContainer.appendChild(typing);
        chatContainer.scrollTop = chatContainer.scrollHeight;

        try {
            const res = await fetch('/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ message: text })
            });
            const data = await res.json();
            typing.remove();
            if (data.success) {
                appendMessage(data.response, 'ai');
            } else {
                appendMessage('Sorry, I encountered an error.', 'ai');
            }
        } catch (err) {
            if (typing) typing.remove();
            appendMessage('Connection error.', 'ai');
        }
    }

    if (sendBtn) {
        sendBtn.addEventListener('click', () => sendMessage(chatInput.value));
    }
    if (chatInput) {
        chatInput.addEventListener('keypress', e => { if (e.key === 'Enter') sendMessage(chatInput.value); });
    }
    suggestionPills.forEach(pill => {
        pill.addEventListener('click', () => sendMessage(pill.textContent));
    });
});
