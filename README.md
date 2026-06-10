# FANET LB-MCR Projesi
 
SDN Kontrollü Çok Yollu Kümeleme Tabanlı Yer-Hava Kooperatif Ağlarda Güvenilir ve Enerji Verimli İletişim

---

## Proje Yapısı

```
fanet_proje/
├── ryu_lb_mcr_controller.py   # Ryu SDN kontrolcüsü (ana algoritma)
├── mininet_fanet_fixed.py     # Mininet LB-MCR topolojisi + ölçüm
├── mininet_aodv_baseline.py   # Mininet AODV karşılaştırması
├── fanet_lb_mcr.cc            # ns-3 C++ simülasyonu
├── ns3_fanet_simulation.py    # ns-3 yardımcı script
├── performance_analysis.py    # Grafik üretici
├── fanet_visualizer.py        # Canlı topoloji görselleştirici ★
└── setup_and_run.sh           # Otomatik çalıştırma scripti
```

---

## Dosyalar Ne İş Yapıyor?

### `ryu_lb_mcr_controller.py` — SDN Kontrolcüsü (Ana Algoritma)
Projenin kalbi. Ryu framework üzerinde çalışır.
- UAV-UGV ağını izler, kümeleme yapar
- Çok yollu (multipath) rotalar hesaplar
- Bağlantı kopunca greedy onarım başlatır
- Metrikleri `/tmp/fanet_results/metrics.csv` dosyasına kaydeder

### `mininet_fanet_fixed.py` — Mininet LB-MCR Topolojisi
5 UAV + 2 UGV hibrit ağını Mininet'te emüle eder.
- Ryu'ya bağlanır (port 6633)
- iperf3 ile throughput, ping ile RTT/paket kaybı ölçer
- Sonuçlar: `/tmp/fanet_results/performance.json`

### `mininet_aodv_baseline.py` — AODV Karşılaştırması
AODV protokolünü simüle eder, LB-MCR ile karşılaştırma için.
- Sonuçlar: `/tmp/fanet_results/aodv_baseline.json`

### `fanet_lb_mcr.cc` — ns-3 C++ Simülasyonu
Paket düzeyinde detaylı simülasyon.
- LB-MCR, AODV, OLSR protokollerini karşılaştırır
- 3, 5, 7, 10 UAV ile ölçeklenebilirlik testi
- Sonuçlar: `/tmp/fanet_results/ns3_<protokol>.csv`

### `fanet_visualizer.py` — Canlı Görselleştirici ★
Mininet çalışırken topolojiyi canlı gösterir.
- UAV hareketi, enerji seviyeleri, aktif linkler
- Küme başlarını ve SDN rotalarını renklendirir
- Anlık metrik paneli (throughput, link sayısı, enerji)

### `performance_analysis.py` — Grafik Üretici
Tüm ölçüm sonuçlarını grafiğe döker.
- Sonuçlar: `/tmp/fanet_results/plots/`

---

## Kurulum Gereksinimleri

```bash
pip3 install ryu networkx matplotlib numpy
sudo apt-get install iperf3 mininet
```

---

## HOCAYA GÖSTERME — Adım Adım

### Terminal 1 — Ryu Kontrolcüsünü Başlat
```bash
cd ~/Desktop/fanet_proje
ryu-manager --ofp-tcp-listen-port 6633 ryu_lb_mcr_controller.py
```
> Ekranda kümeleme ve link logları akmaya başlar.

---

### Terminal 2 — Canlı Görselleştiriciyi Aç
```bash
python3 ~/Desktop/fanet_proje/fanet_visualizer.py
```
> UAV'ların hareket ettiği, enerjinin azaldığı canlı pencere açılır.

---

### Terminal 3 — Mininet Simülasyonunu Çalıştır
```bash
# LB-MCR ölçümü
sudo python3 ~/Desktop/fanet_proje/mininet_fanet_fixed.py

# AODV baseline (karşılaştırma için)
sudo python3 ~/Desktop/fanet_proje/mininet_aodv_baseline.py
```

---

### Terminal 4 — ns-3 Simülasyonları
```bash
cd ~/ns-allinone-3.38/ns-3.38

# LB-MCR
python3 ns3 run "fanet_lb_mcr --protocol=lbmcr --simTime=60 --nUav=5"

# AODV karşılaştırması
python3 ns3 run "fanet_lb_mcr --protocol=aodv --simTime=60 --nUav=5"

# Ölçeklenebilirlik (3,5,7,10 UAV)
for n in 3 5 7 10; do
  python3 ns3 run "fanet_lb_mcr --protocol=lbmcr --simTime=60 --nUav=$n"
done
```

---

### Son Adım — Grafikleri Üret
```bash
cd ~/Desktop/fanet_proje
python3 performance_analysis.py
```

---

## Hızlı Başlatma (Tek Komut)

```bash
cd ~/Desktop/fanet_proje && chmod +x setup_and_run.sh && ./setup_and_run.sh
```

---

## Elde Edilen Sonuçlar

| Metrik | LB-MCR | AODV | İyileştirme |
|--------|--------|------|-------------|
| Throughput | 6.7 Mbps | 1.0 Mbps | **+%550** |
| RTT | 19 ms | 43 ms | **-%56** |
| Paket Kaybı | %3 | %16 | **-%81** |

---

## Sonuç Dosyaları

| Dosya | İçerik |
|-------|--------|
| `/tmp/fanet_results/performance.json` | Mininet LB-MCR ölçümleri |
| `/tmp/fanet_results/aodv_baseline.json` | Mininet AODV ölçümleri |
| `/tmp/fanet_results/ns3_lbmcr.csv` | ns-3 LB-MCR sonuçları |
| `/tmp/fanet_results/plots/` | Tüm grafikler |

```bash
# Sonuçları yedekle (kapanınca silinir!)
cp -r /tmp/fanet_results ~/Desktop/fanet_proje/results/
```

---

# fanet-sdn-lb-mcr
# fanet_proje
# fanet_proje
# fanet_proje
# fanet_proje
