package avtas.amase.network;

import afrl.cmasi.KeyValuePair;
import avtas.lmcp.LMCPObject;
import avtas.xml.Element;
import java.net.InetAddress;
import java.net.Socket;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;

/** Deterministic accept/disconnect changes during the production fan-out loop. */
public final class TcpFanoutChecks extends TcpServer {
    private static final Element results=new Element("TcpFanoutChecks");
    private static int failures;
    private static int port=40000;
    static final class Endpoint extends Socket {
        private final int number=++port;
        @Override public InetAddress getInetAddress() { return InetAddress.getLoopbackAddress(); }
        @Override public int getPort() { return number; }
    }
    final class Peer extends SocketThread {
        final AtomicInteger frames=new AtomicInteger();
        Runnable duringSend;
        Peer() { super(new Endpoint()); }
        @Override public synchronized boolean sendMessage(LMCPObject value) {
            frames.incrementAndGet();
            if(duringSend!=null) { Runnable action=duringSend; duringSend=null; action.run(); }
            return true;
        }
    }
    static void check(String name,boolean passed,String detail) {
        Element row=new Element("Check"); row.setAttribute("name",name);
        row.setAttribute("passed",Boolean.toString(passed)); row.setAttribute("detail",detail);
        results.add(row); if(!passed) failures++;
    }
    static void await(CountDownLatch latch) {
        try { if(!latch.await(5,TimeUnit.SECONDS)) throw new IllegalStateException("Mutation barrier timed out"); }
        catch(InterruptedException error) { throw new IllegalStateException(error); }
    }
    void exercise(boolean incoming,boolean remove) throws Exception {
        Peer first=new Peer(), second=new Peer(), source=new Peer(), late=new Peer();
        socketList.add(first); socketList.add(second); socketList.add(source);
        CountDownLatch entered=new CountDownLatch(1), changed=new CountDownLatch(1);
        first.duringSend=()->{ entered.countDown(); await(changed); };
        Thread mutation=new Thread(()->{
            await(entered);
            if(remove) { second.setRunning(false); socketList.remove(second); }
            else socketList.add(late);
            changed.countDown();
        });
        String label=(incoming?"incoming-fanout":"simulation-broadcast")+(remove?"-disconnect":"-accept");
        mutation.start(); String error="";
        try {
            if(incoming) sendToOthers(new KeyValuePair(),source); else sendMessage(new KeyValuePair());
        } catch(Exception failure) { error=failure.getClass().getName(); }
        mutation.join(6000);
        check(label+"-no-exception",error.isEmpty()&&!mutation.isAlive(),error);
        check(label+"-existing-peer",first.frames.get()==1,"frames="+first.frames);
        check(label+"-source-exclusion",source.frames.get()==(incoming?0:1),"frames="+source.frames);
        check(label+"-snapshot",late.frames.get()==0&&second.frames.get()==(remove?0:1),
              "late="+late.frames+", second="+second.frames);
        if(!remove) {
            if(incoming) sendToOthers(new KeyValuePair(),source); else sendMessage(new KeyValuePair());
            check(label+"-next-message",late.frames.get()==1,"frames="+late.frames);
        }
    }
    void stoppedPeer() {
        Peer stopped=new Peer(), active=new Peer(); stopped.setRunning(false);
        socketList.add(stopped); socketList.add(active);
        sendToOthers(new KeyValuePair(),null);
        check("stopped-peer-pruned",!socketList.contains(stopped)&&stopped.frames.get()==0&&active.frames.get()==1,
              "stopped="+stopped.frames+", active="+active.frames);
    }
    public static void main(String[] args) throws Exception {
        for(boolean incoming:new boolean[]{true,false}) for(boolean remove:new boolean[]{false,true})
            new TcpFanoutChecks().exercise(incoming,remove);
        new TcpFanoutChecks().stoppedPeer();
        results.setAttribute("failures",Integer.toString(failures));
        Files.writeString(Path.of(args[0]),results.toXML(),StandardCharsets.UTF_8);
        System.out.println("TCP fan-out failures="+failures); System.exit(failures==0?0:1);
    }
}
