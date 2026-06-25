import SecureContextProbe from "./SecureContextProbe";

export default function Home() {
  return (
    <main style={{ textAlign: "center" }}>
      <h1 style={{ margin: "0 0 0.5rem" }}>Adept — stack online</h1>
      <SecureContextProbe />
    </main>
  );
}
