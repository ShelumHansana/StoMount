/* ==========================================================================
   StoMount Official Webpage Interactive Application Logic
   Interactive Storage Simulation, Tab Router, Download Engine & UI
   ========================================================================== */

(function () {
  'use strict';

  // State Management for Interactive Visualizer
  const state = {
    sdCapacityGb: 128,
    phoneCapacityGb: 64,
    phoneUsedGb: 58.4,    // 91% Full initially
    sdUsedGb: 4.2,        // 3% Portable data
    isAdopted: false,
    isMigrated: false,
    currentStep: 0,
    isTransferring: false,
    activeTab: 'overview'
  };

  // DOM Elements Cache
  const els = {
    // Tabs
    tabBtns: document.querySelectorAll('.tab-btn'),
    tabPages: document.querySelectorAll('.tab-page'),
    navLinks: document.querySelectorAll('.nav-link'),
    mobileToggle: document.getElementById('mobileToggle'),
    navLinksContainer: document.getElementById('navLinks'),

    // Visualizer Elements
    btnAdopt: document.getElementById('vizBtnAdopt'),
    btnMigrate: document.getElementById('vizBtnMigrate'),
    btnRevert: document.getElementById('vizBtnRevert'),
    btnResetSim: document.getElementById('vizBtnReset'),
    
    phoneBox: document.getElementById('vizPhoneBox'),
    sdBox: document.getElementById('vizSdBox'),
    conduitStream: document.getElementById('vizConduitStream'),
    conduitLabel: document.getElementById('vizConduitLabel'),
    
    phoneFillSys: document.getElementById('meterPhoneSys'),
    phoneFillApps: document.getElementById('meterPhoneApps'),
    phoneBadge: document.getElementById('vizPhoneBadge'),
    phoneStatsUsed: document.getElementById('vizPhoneUsed'),
    phoneStatsTotal: document.getElementById('vizPhoneTotal'),
    phoneStatusText: document.getElementById('vizPhoneStatus'),

    sdFillAdopted: document.getElementById('meterSdAdopted'),
    sdBadge: document.getElementById('vizSdBadge'),
    sdStatsUsed: document.getElementById('vizSdUsed'),
    sdStatsTotal: document.getElementById('vizSdTotal'),
    sdStatusText: document.getElementById('vizSdStatus'),

    terminalLogs: document.getElementById('vizTerminalLogs'),
    chips: document.querySelectorAll('.chip[data-sd-size]'),

    // Modals & Toasts
    modalOverlay: document.getElementById('downloadModal'),
    modalClose: document.getElementById('modalClose'),
    toastContainer: document.getElementById('toastContainer'),
    faqItems: document.querySelectorAll('.faq-item')
  };

  /* ==========================================================================
     Tab / Multi-Page View Switching
     ========================================================================== */
  function switchTab(targetId) {
    if (!targetId) return;
    state.activeTab = targetId;

    // Update Tab Buttons
    els.tabBtns.forEach(btn => {
      if (btn.dataset.target === targetId) {
        btn.classList.add('active');
      } else {
        btn.classList.remove('active');
      }
    });

    // Update Nav Links
    els.navLinks.forEach(link => {
      if (link.getAttribute('href') === `#${targetId}`) {
        link.classList.add('active');
      } else {
        link.classList.remove('active');
      }
    });

    // Switch Pages
    els.tabPages.forEach(page => {
      if (page.id === `page-${targetId}`) {
        page.classList.add('active');
      } else {
        page.classList.remove('active');
      }
    });

    // Close mobile menu if open
    if (els.navLinksContainer) {
      els.navLinksContainer.classList.remove('open');
    }

    // Scroll to view-tabs-bar if user clicked from nav
    const tabsBar = document.getElementById('tabsBar');
    if (tabsBar && window.scrollY > 400) {
      tabsBar.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  }

  /* ==========================================================================
     Storage Visualizer Simulator Logic
     ========================================================================== */
  function logTerminal(type, text) {
    if (!els.terminalLogs) return;
    const now = new Date();
    const timeStr = `[${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}:${String(now.getSeconds()).padStart(2, '0')}]`;
    
    const div = document.createElement('div');
    if (type === 'cmd') {
      div.innerHTML = `${timeStr} <span class="log-cmd">$ ${text}</span>`;
    } else if (type === 'info') {
      div.innerHTML = `${timeStr} <span class="log-info">✓ ${text}</span>`;
    } else if (type === 'warn') {
      div.innerHTML = `${timeStr} <span class="log-warn">ℹ ${text}</span>`;
    } else {
      div.innerHTML = `${timeStr} ${text}`;
    }
    
    els.terminalLogs.appendChild(div);
    els.terminalLogs.scrollTop = els.terminalLogs.scrollHeight;
  }

  function updateVisualizerUI() {
    // Phone stats
    const phonePercent = Math.round((state.phoneUsedGb / state.phoneCapacityGb) * 100);
    const systemGb = 16.0;
    const appsGb = Math.max(0, state.phoneUsedGb - systemGb);
    
    const sysPercent = (systemGb / state.phoneCapacityGb) * 100;
    const appsPercent = (appsGb / state.phoneCapacityGb) * 100;

    els.phoneFillSys.style.width = `${sysPercent}%`;
    els.phoneFillApps.style.width = `${appsPercent}%`;
    
    els.phoneStatsUsed.textContent = `${state.phoneUsedGb.toFixed(1)} GB`;
    els.phoneStatsTotal.textContent = `${state.phoneCapacityGb} GB (${phonePercent}% used)`;

    if (phonePercent > 85) {
      els.phoneBadge.textContent = 'Storage Full (91%)';
      els.phoneBadge.className = 'storage-badge badge-critical';
      els.phoneStatusText.textContent = 'Critical: Apps cannot update & camera blocked';
      els.phoneFillApps.style.background = 'linear-gradient(90deg, #F59E0B, #EF4444)';
    } else {
      els.phoneBadge.textContent = 'Healthy (34%)';
      els.phoneBadge.className = 'storage-badge badge-success';
      els.phoneStatusText.textContent = 'Spacious: System and OS running smoothly';
      els.phoneFillApps.style.background = 'linear-gradient(90deg, #10B981, #059669)';
    }

    // SD Card stats
    const sdPercent = Math.round((state.sdUsedGb / state.sdCapacityGb) * 100);
    els.sdFillAdopted.style.width = `${sdPercent}%`;
    els.sdStatsUsed.textContent = `${state.sdUsedGb.toFixed(1)} GB`;
    els.sdStatsTotal.textContent = `${state.sdCapacityGb} GB (${sdPercent}% used)`;

    if (state.isAdopted) {
      if (state.isMigrated) {
        els.sdBadge.textContent = 'Adopted & Active';
        els.sdBadge.className = 'storage-badge badge-success';
        els.sdStatusText.textContent = 'Adopted Storage: 45 Apps & Primary Media running here';
      } else {
        els.sdBadge.textContent = 'Adopted (Empty)';
        els.sdBadge.className = 'storage-badge badge-cyan';
        els.sdStatusText.textContent = 'Encrypted Private Volume ready for Migration';
      }
    } else {
      els.sdBadge.textContent = 'Standard Portable (FAT32)';
      els.sdBadge.className = 'storage-badge badge-neutral';
      els.sdStatusText.textContent = 'Portable Media only (Apps forbidden by OS)';
    }

    // Action button states
    if (state.isTransferring) {
      els.btnAdopt.disabled = true;
      els.btnMigrate.disabled = true;
      els.btnRevert.disabled = true;
      return;
    }

    els.btnAdopt.disabled = state.isAdopted;
    els.btnMigrate.disabled = !state.isAdopted || state.isMigrated;
    els.btnRevert.disabled = !state.isAdopted && !state.isMigrated;

    if (state.isAdopted) {
      els.btnAdopt.innerHTML = '<span>✓ SD Card Adopted</span>';
      els.btnAdopt.classList.remove('btn-primary');
      els.btnAdopt.classList.add('btn-secondary');
    } else {
      els.btnAdopt.innerHTML = '<span>⚡ 1. Mount SD as Internal</span>';
      els.btnAdopt.classList.add('btn-primary');
      els.btnAdopt.classList.remove('btn-secondary');
    }

    if (state.isMigrated) {
      els.btnMigrate.innerHTML = '<span>✓ Content Migrated</span>';
      els.btnMigrate.classList.remove('btn-emerald');
      els.btnMigrate.classList.add('btn-secondary');
    } else {
      els.btnMigrate.innerHTML = '<span>🚀 2. Move Apps & Content</span>';
      els.btnMigrate.classList.add('btn-emerald');
      els.btnMigrate.classList.remove('btn-secondary');
    }
  }

  // Action: Step 1 Adopt SD Card
  function handleAdopt() {
    if (state.isAdopted || state.isTransferring) return;
    state.isTransferring = true;
    updateVisualizerUI();

    logTerminal('cmd', 'adb shell sm list-disks adoptable');
    logTerminal('info', 'Found hardware disk:179,64 (Adoptable MicroSD)');
    logTerminal('cmd', 'adb shell sm partition disk:179,64 private');
    logTerminal('warn', 'Formatting & initializing cryptographic partition...');

    els.sdBox.classList.add('active-pulse');

    setTimeout(() => {
      const mockUuid = 'f8a92bc1-8930-4e3d-b4f2-51a80c982d41';
      logTerminal('info', `Adopted SD volume mounted at /mnt/expand/${mockUuid}`);
      logTerminal('info', 'Adopted UUID detected & saved. Ready for Step 2!');

      state.isAdopted = true;
      state.isTransferring = false;
      els.sdBox.classList.remove('active-pulse');
      showToast('MicroSD Card adopted successfully as Internal Storage!');
      updateVisualizerUI();
    }, 1200);
  }

  // Action: Step 2 Migrate Apps
  function handleMigrate() {
    if (!state.isAdopted || state.isMigrated || state.isTransferring) return;
    state.isTransferring = true;
    updateVisualizerUI();

    logTerminal('cmd', 'adb shell pm list packages -3');
    logTerminal('info', 'Discovered 45 movable 3rd-party user applications');
    logTerminal('cmd', 'adb shell pm move-package com.spotify.music [uuid]');
    logTerminal('cmd', 'adb shell pm move-package com.instagram.android [uuid]');
    logTerminal('cmd', 'adb shell pm move-primary-storage [uuid]');

    // Activate conduit animation
    els.conduitStream.className = 'conduit-stream streaming-forward';
    els.conduitLabel.textContent = 'Migrating 45 Apps...';
    els.phoneBox.classList.add('active-pulse');
    els.sdBox.classList.add('active-pulse');

    // Simulate animated transfer steps
    let step = 0;
    const interval = setInterval(() => {
      step++;
      if (step === 1) {
        state.phoneUsedGb = 46.0;
        state.sdUsedGb = 16.6;
        updateVisualizerUI();
      } else if (step === 2) {
        state.phoneUsedGb = 32.0;
        state.sdUsedGb = 30.6;
        updateVisualizerUI();
      } else if (step === 3) {
        state.phoneUsedGb = 21.8; // Liberated!
        state.sdUsedGb = 40.8;
        state.isMigrated = true;
        state.isTransferring = false;
        clearInterval(interval);

        els.conduitStream.className = 'conduit-stream';
        els.conduitLabel.textContent = 'ADB Connected';
        els.phoneBox.classList.remove('active-pulse');
        els.sdBox.classList.remove('active-pulse');

        logTerminal('info', 'SUCCESS! 45 Apps and 36.6 GB liberated from Internal Storage.');
        showToast('🎉 All apps & content migrated! 36.6 GB storage freed!');
        updateVisualizerUI();
      }
    }, 600);
  }

  // Action: Revert & Reset
  function handleRevert() {
    if (state.isTransferring) return;
    state.isTransferring = true;
    updateVisualizerUI();

    logTerminal('cmd', 'adb shell pm move-package <all> internal');
    logTerminal('warn', 'Reverting apps & primary storage back to internal memory...');

    els.conduitStream.className = 'conduit-stream streaming-backward';
    els.conduitLabel.textContent = 'Restoring...';

    setTimeout(() => {
      logTerminal('cmd', 'adb shell sm partition disk:179,64 public');
      logTerminal('info', 'MicroSD formatted back to standard portable FAT32/exFAT.');
      logTerminal('info', 'Default factory state restored.');

      state.phoneUsedGb = 58.4;
      state.sdUsedGb = 4.2;
      state.isAdopted = false;
      state.isMigrated = false;
      state.isTransferring = false;

      els.conduitStream.className = 'conduit-stream';
      els.conduitLabel.textContent = 'ADB Connected';
      showToast('Storage safely restored to original factory state.');
      updateVisualizerUI();
    }, 1200);
  }

  // Reset Simulation
  function handleResetSim() {
    state.phoneUsedGb = 58.4;
    state.sdUsedGb = 4.2;
    state.isAdopted = false;
    state.isMigrated = false;
    state.isTransferring = false;
    els.conduitStream.className = 'conduit-stream';
    els.conduitLabel.textContent = 'ADB Connected';
    if (els.terminalLogs) {
      els.terminalLogs.innerHTML = `
        <div class="terminal-header">
          <span>StoMount Interactive Daemon Console</span>
          <span>ONLINE</span>
        </div>
        <div>[00:00:01] <span class="log-info">Device connected: Galaxy A01 (SM-A015G)</span></div>
        <div>[00:00:02] <span class="log-warn">Internal Memory warning: 91% Full (58.4 GB / 64 GB)</span></div>
        <div>[00:00:03] <span class="log-cmd">MicroSD Card detected: 128 GB (Portable)</span></div>
      `;
    }
    showToast('Simulation reset to initial state.');
    updateVisualizerUI();
  }

  // Change SD Card Size Chip
  function handleSdSizeChange(e) {
    const size = parseInt(e.target.dataset.sdSize, 10);
    if (!size) return;
    state.sdCapacityGb = size;

    els.chips.forEach(c => c.classList.remove('active'));
    e.target.classList.add('active');

    logTerminal('warn', `Simulated SD Card size changed to ${size} GB.`);
    updateVisualizerUI();
  }

  /* ==========================================================================
     Toast Notifications
     ========================================================================== */
  function showToast(message) {
    if (!els.toastContainer) return;
    const toast = document.createElement('div');
    toast.className = 'toast';
    toast.innerHTML = `
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#00F0FF" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path>
        <polyline points="22 4 12 14.01 9 11.01"></polyline>
      </svg>
      <span>${message}</span>
    `;
    els.toastContainer.appendChild(toast);
    
    // Animate in
    setTimeout(() => toast.classList.add('show'), 10);

    // Auto dismiss
    setTimeout(() => {
      toast.classList.remove('show');
      setTimeout(() => toast.remove(), 300);
    }, 3800);
  }

  /* ==========================================================================
     Download Modal & Triggers
     ========================================================================== */
  window.openDownloadModal = function (packageName) {
    if (!els.modalOverlay) return;
    const pkgTitle = document.getElementById('modalPkgTitle');
    const pkgDesc = document.getElementById('modalPkgDesc');
    const pkgBtn = document.getElementById('modalDownloadBtn');

    if (packageName === 'portable') {
      pkgTitle.textContent = 'StoMount.exe (Standalone Portable)';
      pkgDesc.textContent = 'No installation needed. Single double-click executable with embedded Google ADB.';
      pkgBtn.href = 'downloads/StoMount.exe';
      pkgBtn.download = 'StoMount.exe';
    } else if (packageName === 'zip') {
      pkgTitle.textContent = 'StoMount-v1.2-Windows.zip (Full Bundle)';
      pkgDesc.textContent = 'Complete distribution bundle including installer, standalone exe, and high-res icon assets.';
      pkgBtn.href = 'downloads/StoMount-v1.2-Windows.zip';
      pkgBtn.download = 'StoMount-v1.2-Windows.zip';
    } else {
      pkgTitle.textContent = 'StoMount_Setup.exe (Windows Installer)';
      pkgDesc.textContent = 'Standard Windows setup with desktop icon, Start Menu shortcut, and automatic updates.';
      pkgBtn.href = 'downloads/StoMount_Setup.exe';
      pkgBtn.download = 'StoMount_Setup.exe';
    }

    els.modalOverlay.classList.add('active');
  };

  window.closeDownloadModal = function () {
    if (els.modalOverlay) {
      els.modalOverlay.classList.remove('active');
    }
  };

  window.copyChecksum = function (hash) {
    navigator.clipboard.writeText(hash).then(() => {
      showToast('SHA-256 Checksum copied to clipboard!');
    }).catch(() => {
      showToast('Checksum ready to copy.');
    });
  };

  /* ==========================================================================
     FAQ Accordion
     ========================================================================== */
  function initFaq() {
    els.faqItems.forEach(item => {
      const btn = item.querySelector('.faq-question');
      const ans = item.querySelector('.faq-answer');
      if (!btn || !ans) return;

      btn.addEventListener('click', () => {
        const isOpen = item.classList.contains('open');
        // Close others
        els.faqItems.forEach(i => {
          i.classList.remove('open');
          const a = i.querySelector('.faq-answer');
          if (a) a.style.maxHeight = null;
        });

        if (!isOpen) {
          item.classList.add('open');
          ans.style.maxHeight = ans.scrollHeight + 'px';
        }
      });
    });
  }

  /* ==========================================================================
     Event Listeners Initialization
     ========================================================================== */
  function initEvents() {
    // Tab switching
    els.tabBtns.forEach(btn => {
      btn.addEventListener('click', () => switchTab(btn.dataset.target));
    });

    els.navLinks.forEach(link => {
      link.addEventListener('click', (e) => {
        const href = link.getAttribute('href');
        if (href && href.startsWith('#')) {
          e.preventDefault();
          const target = href.substring(1);
          switchTab(target);
        }
      });
    });

    // Mobile menu toggle
    if (els.mobileToggle && els.navLinksContainer) {
      els.mobileToggle.addEventListener('click', () => {
        els.navLinksContainer.classList.toggle('open');
      });
    }

    // Visualizer buttons
    if (els.btnAdopt) els.btnAdopt.addEventListener('click', handleAdopt);
    if (els.btnMigrate) els.btnMigrate.addEventListener('click', handleMigrate);
    if (els.btnRevert) els.btnRevert.addEventListener('click', handleRevert);
    if (els.btnResetSim) els.btnResetSim.addEventListener('click', handleResetSim);

    els.chips.forEach(chip => {
      chip.addEventListener('click', handleSdSizeChange);
    });

    // Modal Close
    if (els.modalClose) {
      els.modalClose.addEventListener('click', window.closeDownloadModal);
    }
    if (els.modalOverlay) {
      els.modalOverlay.addEventListener('click', (e) => {
        if (e.target === els.modalOverlay) window.closeDownloadModal();
      });
    }

    // Keyboard navigation (Escape closes modal)
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') window.closeDownloadModal();
    });

    // Check URL hash for initial tab
    const hash = window.location.hash.replace('#', '');
    if (hash && ['overview', 'visualizer', 'workflow', 'compatibility', 'downloads', 'faq'].includes(hash)) {
      switchTab(hash);
    }
  }

  // Initialize on DOM Ready
  document.addEventListener('DOMContentLoaded', () => {
    initEvents();
    initFaq();
    updateVisualizerUI();
  });

})();
