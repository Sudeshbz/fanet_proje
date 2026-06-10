#!/usr/bin/env python3
import os, sys, time, json
from mininet.log import setLogLevel, info
from mininet.node import RemoteController, OVSKernelSwitch
from mininet.link import TCLink
from mininet.net import Mininet
from mininet.cli import CLI

RESULTS_DIR = "/tmp/fanet_results"

def build_topology():
    os.makedirs(RESULTS_DIR, exist_ok=True)
    setLogLevel("info")
    info("*** AODV Baseline Mininet baslatiliyor...\n")

    net = Mininet(controller=RemoteController,
                  switch=OVSKernelSwitch,
                  link=TCLink, autoSetMacs=True)

    c0 = net.addController("c0", controller=RemoteController,
                           ip="127.0.0.1", port=6633)

    uavs = []
    for i in range(1,6):
        uavs.append(net.addHost(f"uav{i}", ip=f"10.0.0.{i}/8"))
    ugvs = []
    for i in range(1,3):
        ugvs.append(net.addHost(f"ugv{i}", ip=f"10.0.0.{10+i}/8"))

    s1 = net.addSwitch("s1", protocols="OpenFlow13")

    # AODV baseline: daha yüksek delay ve loss (AODV'nin zayıflıklarını simüle et)
    for uav in uavs:
        net.addLink(uav, s1, bw=54, delay="15ms", loss=5)
    for ugv in ugvs:
        net.addLink(ugv, s1, bw=100, delay="5ms", loss=1)

    net.start()
    time.sleep(2)

    results = []
    info("*** AODV iperf3 testi...\n")
    ugvs[0].cmd("iperf3 -s -D -p 5201")
    time.sleep(1)
    for uav in uavs:
        out = uav.cmd(f"iperf3 -c {ugvs[0].IP()} -p 5201 -t 10 -J 2>/dev/null")
        try:
            d = json.loads(out)
            bw = d["end"]["sum_received"]["bits_per_second"]/1e6
            info(f"    {uav.name}: {bw:.2f} Mbps\n")
            results.append({"src":uav.name,"bw_mbps":round(bw,3),"protocol":"aodv"})
        except:
            info(f"    {uav.name}: hata\n")
    ugvs[0].cmd("pkill iperf3")

    info("*** AODV ping testi...\n")
    for uav in uavs:
        out = uav.cmd("ping -c 20 -i 0.1 10.0.0.11 2>/dev/null")
        rtt, loss = 0.0, 0.0
        for line in out.split("\n"):
            if "rtt" in line.lower():
                try: rtt = float(line.split("/")[4])
                except: pass
            if "packet loss" in line:
                try: loss = float(line.split("%")[0].split()[-1])
                except: pass
        info(f"    {uav.name}: RTT={rtt:.2f}ms loss={loss:.1f}%\n")
        results.append({"src":uav.name,"rtt_ms":rtt,"loss_pct":loss,"protocol":"aodv"})

    with open(f"{RESULTS_DIR}/aodv_baseline.json","w") as f:
        json.dump(results, f, indent=2)
    info(f"\n*** AODV baseline kaydedildi\n")

    net.stop()

if __name__ == "__main__":
    if os.geteuid() != 0:
        print("sudo python3 mininet_aodv_baseline.py")
        sys.exit(1)
    build_topology()
