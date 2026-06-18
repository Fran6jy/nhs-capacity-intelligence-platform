/** Animated aurora + grid backdrop for the immersive feel. */
export default function Background() {
  return (
    <div className="fixed inset-0 -z-10 overflow-hidden">
      <div className="absolute -top-40 -left-40 h-[40rem] w-[40rem] rounded-full bg-nhs-blue/30 blur-[140px] animate-aurora" />
      <div className="absolute top-1/3 -right-40 h-[36rem] w-[36rem] rounded-full bg-nhs-cyan/25 blur-[140px] animate-aurora-slow" />
      <div className="absolute bottom-[-10rem] left-1/3 h-[32rem] w-[32rem] rounded-full bg-indigo-600/20 blur-[150px] animate-aurora" />
      <div
        className="absolute inset-0 opacity-[0.04]"
        style={{
          backgroundImage:
            "linear-gradient(rgba(255,255,255,0.6) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.6) 1px, transparent 1px)",
          backgroundSize: "44px 44px",
        }}
      />
    </div>
  );
}
