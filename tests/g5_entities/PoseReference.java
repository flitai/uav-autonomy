import avtas.math.Euler;
import avtas.math.Vector3;
// Independent reference calls the actual AMASE Euler implementation from the formal JAR.
public class PoseReference {
    public static void main(String[] args) {
        double[][] samples={{0,0,0},{90,0,0},{180,0,0},{270,0,0},{0,10,0},{0,-10,0},{0,0,20},{0,0,-20},{359,15,-30},{35,-25,45}};
        System.out.print("[");
        for(int i=0;i<samples.length;i++) {
            double[] a=samples[i];Euler e=new Euler(Math.toRadians(a[0]),Math.toRadians(a[1]),Math.toRadians(a[2]));
            if(i>0)System.out.print(",");System.out.print("{\"heading\":"+a[0]+",\"pitch\":"+a[1]+",\"roll\":"+a[2]+",\"nedColumns\":[");
            Vector3[] units={new Vector3(1,0,0),new Vector3(0,-1,0),new Vector3(0,0,-1)};
            for(int k=0;k<3;k++){Vector3 v=e.getDxDyDz(units[k]);if(k>0)System.out.print(",");System.out.print("["+v.get1()+","+v.get2()+","+v.get3()+"]");}
            System.out.print("]}");
        }
        System.out.println("]");
    }
}
