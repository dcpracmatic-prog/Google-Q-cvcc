// MaxCut de referencia — programa de Arturo, pegado el 2026-11-11.
// Se guarda VERBATIM como referencia del port a Python
// (auto_mvp/maxcut.py). No se ha modificado.
// Verificado: n=24 seed=101, exact_best=76.3397044423,
// morph_best=76.3397044422, gap 9.95e-11, certificate_exact=PASS,
// speedup 4,376.6x. Compilar: g++ -O2 -o maxcut maxcut_reference.cpp
#include <bits/stdc++.h>
using namespace std;
struct Graph{int n; vector<double>w; double& W(int i,int j){return w[(size_t)i*n+j];} const double& W(int i,int j)const{return w[(size_t)i*n+j];}};
struct Out{double best; uint64_t steps; double sec; vector<int8_t>x;};
Graph make_graph(int n,uint64_t seed,double p=0.35){mt19937_64 r(seed); uniform_real_distribution<double> u(0,1), ww(0.2,2.0); Graph g{n,vector<double>((size_t)n*n,0)}; for(int i=0;i<n;i++)for(int j=i+1;j<n;j++)if(u(r)<p){double v=ww(r);g.W(i,j)=g.W(j,i)=v;} return g;}
double cut(const Graph&g,const vector<int8_t>&x){double c=0;for(int i=0;i<g.n;i++)for(int j=i+1;j<g.n;j++)if(x[i]!=x[j])c+=g.W(i,j);return c;}
Out exact(const Graph&g){int n=g.n;uint64_t N=1ULL<<n;vector<int8_t>x(n,-1);vector<double>gain(n);for(int i=0;i<n;i++){double s=0;for(int j=0;j<n;j++)if(i!=j)s+=g.W(i,j)*(x[j]==x[i]?1.0:-1.0);gain[i]=s;}double c=cut(g,x),best=c;vector<int8_t>bx=x;auto t=chrono::steady_clock::now();for(uint64_t k=1;k<N;k++){int b=__builtin_ctzll(k);double dc=gain[b];x[b]=-x[b];c+=dc;gain[b]=-gain[b];for(int j=0;j<n;j++)if(j!=b){ // flipping b changes j's flip gain by +/- 2w
 gain[j] += (x[j]==x[b] ? 2.0*g.W(j,b) : -2.0*g.W(j,b)); }
 if(c>best){best=c;bx=x;}}
 double sec=chrono::duration<double>(chrono::steady_clock::now()-t).count();return{best,N,sec,bx};}
Out morph(const Graph&g,uint64_t seed,int restarts,int steps){
 mt19937_64 r(seed); uniform_real_distribution<double>u(0,1); uniform_int_distribution<int>di(0,g.n-1);
 double best=-1; uint64_t evals=0; vector<int8_t>bx(g.n); auto t=chrono::steady_clock::now();
 for(int rr=0;rr<restarts;rr++){
  vector<int8_t>x(g.n); for(auto &v:x)v=u(r)<.5?-1:1;
  vector<double>gain(g.n); for(int i=0;i<g.n;i++){double s=0;for(int j=0;j<g.n;j++)if(i!=j)s+=g.W(i,j)*(x[j]==x[i]?1.0:-1.0);gain[i]=s;}
  double c=cut(g,x); if(c>best){best=c;bx=x;}
  // Intensification: repeatedly flip the best improving variable.
  for(int s=0;s<steps;s++){
   int bi=0; double bg=gain[0]; for(int i=1;i<g.n;i++)if(gain[i]>bg){bg=gain[i];bi=i;}
   if(bg<=1e-12) break;
   x[bi]=-x[bi]; c+=bg; gain[bi]=-gain[bi];
   for(int j=0;j<g.n;j++)if(j!=bi)gain[j]+=(x[j]==x[bi]?2.0*g.W(j,bi):-2.0*g.W(j,bi));
   evals++; if(c>best){best=c;bx=x;}
  }
  // Diversification: random perturbation then continue.
  for(int q=0;q<g.n/4;q++){int i=di(r);x[i]=-x[i];}
 }
 double sec=chrono::duration<double>(chrono::steady_clock::now()-t).count(); return {best,evals,sec,bx};
}
int main(int argc,char**argv){int n=24;uint64_t seed=101;int restarts=64,steps=5000;if(argc>1)n=atoi(argv[1]);if(argc>2)seed=strtoull(argv[2],0,10);if(argc>3)restarts=atoi(argv[3]);if(argc>4)steps=atoi(argv[4]);auto g=make_graph(n,seed);auto e=exact(g);auto m=morph(g,seed^0x9e3779b97f4a7c15ULL,restarts,steps);cout<<setprecision(12)<<"scenario=maxcut n="<<n<<" seed="<<seed<<" edges=";int edges=0;for(int i=0;i<n;i++)for(int j=i+1;j<n;j++)edges+=g.W(i,j)>0;cout<<edges<<"\n";cout<<"exact_best="<<e.best<<" exact_states="<<e.steps<<" exact_sec="<<e.sec<<"\n";cout<<"morph_best="<<m.best<<" morph_steps="<<m.steps<<" morph_sec="<<m.sec<<"\n";cout<<"gap="<<e.best-m.best<<" relative_gap="<<(e.best-m.best)/max(1e-12,abs(e.best))<<" step_reduction="<<(1.0-(double)m.steps/e.steps)<<" speedup="<<e.sec/m.sec<<"\n";cout<<"certificate_exact="<<(fabs(e.best-m.best)<1e-9?"PASS":"FAIL")<<"\n";}
