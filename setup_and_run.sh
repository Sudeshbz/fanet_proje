#!/bin/bash
# =============================================================
# FANET LB-MCR Kurulum & Çalıştırma Scripti
# TÜBİTAK 2209-A - Sude Filikci
# Yalova Üniversitesi
# =============================================================
# Kullanım:
#   chmod +x setup_and_run.sh
#   ./setup_and_run.sh          # Tam kurulum
#   ./setup_and_run.sh --ryu    # Sadece Ryu çalıştır
#   ./setup_and_run.sh --ns3    # Sadece ns-3 scripti üret
#   ./setup_and_run.sh --plot   # Sadece grafik üret
# =============================================================

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RESULTS_DIR="/tmp/fanet_results"
PLOTS_DIR="$RESULTS_DIR/plots"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

info()    { echo -e "${BLUE}[INFO]${NC}  $1"; }
success() { echo -e "${GREEN}[OK]${NC}    $1"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $1"; }
error()   { echo -e "${RED}[ERR]${NC}   $1"; }

echo ""
echo "======================================================"
echo "  FANET LB-MCR Projesi - Kurulum & Çalıştırma"
echo "  TÜBİTAK 2209-A"
echo "======================================================"
echo ""

mkdir -p "$RESULTS_DIR" "$PLOTS_DIR"

# ─── Argüman kontrolü ────────────────────────────────────────
MODE="all"
case "${1:-}" in
  --ryu)  MODE="ryu"  ;;
  --ns3)  MODE="ns3"  ;;
  --plot) MODE="plot" ;;
  --help)
    echo "Kullanım: $0 [--ryu|--ns3|--plot|--help]"
    echo "  (argümansız) : tam kurulum + tüm modüller"
    exit 0 ;;
esac

# ─── Python Bağımlılıkları ───────────────────────────────────
install_python_deps() {
  info "Python bağımlılıkları kuruluyor..."
  pip3 install --quiet --upgrade \
    networkx matplotlib numpy \
    2>/dev/null || pip install --quiet \
    networkx matplotlib numpy

  # Ryu için
  pip3 install --quiet ryu 2>/dev/null \
    || warn "Ryu kurulumu başarısız (zaten kurulu olabilir)"

  success "Python bağımlılıkları hazır"
}

# ─── Mininet-WiFi Kontrol ────────────────────────────────────
check_mininet_wifi() {
  if python3 -c "import mn_wifi" 2>/dev/null; then
    success "Mininet-WiFi kurulu"
    return 0
  else
    warn "Mininet-WiFi kurulu değil."
    echo "  Kurulum için:"
    echo "    git clone https://github.com/intrig-unicamp/mininet-wifi"
    echo "    cd mininet-wifi && sudo util/install.sh -Wlnfv"
    return 1
  fi
}

# ─── ns-3 Kontrol ────────────────────────────────────────────
check_ns3() {
  if command -v ns3 &>/dev/null || [ -f "$HOME/ns-3/waf" ]; then
    success "ns-3 kurulu"
    return 0
  else
    warn "ns-3 kurulu değil."
    echo "  Kurulum için:"
    echo "    wget https://www.nsnam.org/releases/ns-allinone-3.38.tar.bz2"
    echo "    tar xf ns-allinone-3.38.tar.bz2"
    echo "    cd ns-allinone-3.38 && ./build.py --enable-examples"
    return 1
  fi
}

# ─── Ryu Çalıştır ────────────────────────────────────────────
run_ryu_controller() {
  info "Ryu SDN kontrolcüsü başlatılıyor..."
  if ! command -v ryu-manager &>/dev/null; then
    warn "ryu-manager bulunamadı. Kurulum: pip3 install ryu"
    return 1
  fi

  # Arka planda çalıştır
  nohup ryu-manager \
    --ofp-tcp-listen-port 6633 \
    --observe-links \
    "$SCRIPT_DIR/ryu_lb_mcr_controller.py" \
    > "$RESULTS_DIR/ryu.log" 2>&1 &

  RYU_PID=$!
  echo $RYU_PID > "$RESULTS_DIR/ryu.pid"
  sleep 3

  if kill -0 $RYU_PID 2>/dev/null; then
    success "Ryu kontrolcüsü çalışıyor (PID=$RYU_PID)"
    info "Log: $RESULTS_DIR/ryu.log"
    return 0
  else
    error "Ryu başlatılamadı. Log: $RESULTS_DIR/ryu.log"
    return 1
  fi
}

# ─── Mininet Çalıştır ─────────────────────────────────────────
run_mininet() {
  info "Mininet-WiFi topolojisi başlatılıyor..."
  if check_mininet_wifi; then
    if [ "$EUID" -ne 0 ]; then
      warn "Root yetkisi gerekli. sudo ile çalıştırın."
      echo "  sudo python3 $SCRIPT_DIR/mininet_fanet_topology.py"
    else
      python3 "$SCRIPT_DIR/mininet_fanet_topology.py"
    fi
  fi
}

# ─── ns-3 Script Üret/Çalıştır ───────────────────────────────
run_ns3() {
  info "ns-3 simülasyonu..."
  python3 "$SCRIPT_DIR/ns3_fanet_simulation.py"

  # C++ script üretildiyse kopyala
  if [ -f "/home/ubuntu/ns3_fanet_lb_mcr.cc" ]; then
    success "ns-3 C++ script üretildi: /home/ubuntu/ns3_fanet_lb_mcr.cc"

    # ns-3 kuruluysa otomatik çalıştır
    NS3_DIR=""
    for d in "$HOME"/ns-allinone*/ns-3.*; do
      [ -f "$d/waf" ] && NS3_DIR="$d" && break
    done

    if [ -n "$NS3_DIR" ]; then
      info "ns-3 bulundu: $NS3_DIR"
      cp /home/ubuntu/ns3_fanet_lb_mcr.cc "$NS3_DIR/scratch/"
      cd "$NS3_DIR"
      info "Build ediliyor..."
      ./waf build 2>/dev/null
      info "LB-MCR çalışıyor..."
      ./waf --run "fanet_lb_mcr --protocol=lbmcr --simTime=60" \
        2>&1 | tee "$RESULTS_DIR/ns3_lbmcr.log"
      info "AODV baseline..."
      ./waf --run "fanet_lb_mcr --protocol=aodv --simTime=60" \
        2>&1 | tee "$RESULTS_DIR/ns3_aodv.log"
      info "OLSR baseline..."
      ./waf --run "fanet_lb_mcr --protocol=olsr --simTime=60" \
        2>&1 | tee "$RESULTS_DIR/ns3_olsr.log"
      success "ns-3 simülasyonları tamamlandı"
      cd "$SCRIPT_DIR"
    fi
  fi
}

# ─── Performans Analizi ───────────────────────────────────────
run_analysis() {
  info "Performans analizi ve grafik oluşturuluyor..."
  python3 "$SCRIPT_DIR/performance_analysis.py"
  success "Grafikler: $PLOTS_DIR"

  echo ""
  echo "  Üretilen grafikler:"
  ls "$PLOTS_DIR"/*.png 2>/dev/null | while read f; do
    echo "    $(basename $f)"
  done
}

# ─── Ryu Durdur ─────────────────────────────────────────────
stop_ryu() {
  if [ -f "$RESULTS_DIR/ryu.pid" ]; then
    PID=$(cat "$RESULTS_DIR/ryu.pid")
    kill $PID 2>/dev/null && info "Ryu durduruldu (PID=$PID)"
    rm -f "$RESULTS_DIR/ryu.pid"
  fi
}

# ─── Ana Akış ─────────────────────────────────────────────────
trap stop_ryu EXIT

case "$MODE" in
  ryu)
    install_python_deps
    run_ryu_controller
    info "Ryu çalışıyor. Durdurmak için: Ctrl+C"
    wait
    ;;
  ns3)
    install_python_deps
    run_ns3
    ;;
  plot)
    install_python_deps
    run_analysis
    ;;
  all)
    install_python_deps
    check_mininet_wifi || true
    check_ns3          || true

    # 1. Ryu Kontrolcüsü
    run_ryu_controller || warn "Ryu olmadan devam ediliyor"

    # 2. ns-3 Simülasyonu
    run_ns3

    # 3. Mininet (root gerektirir, opsiyonel)
    if [ "$EUID" -eq 0 ]; then
      run_mininet
    else
      warn "Mininet için root gerekli. Atlanıyor."
      echo "  Manuel: sudo python3 $SCRIPT_DIR/mininet_fanet_topology.py"
    fi

    # 4. Analiz & Grafik
    run_analysis

    echo ""
    echo "======================================================"
    success "PROJE TAMAMLANDI"
    echo "======================================================"
    echo "  Sonuçlar : $RESULTS_DIR"
    echo "  Grafikler: $PLOTS_DIR"
    echo ""
    ;;
esac
