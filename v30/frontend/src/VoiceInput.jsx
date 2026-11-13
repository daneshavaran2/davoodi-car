import React,{useEffect,useRef,useState} from 'react';

/* Browser-native Persian speech recognition. The DavoodiCar API receives
   only the final recognized text, never microphone audio. Browser vendors
   may process audio through their own speech service. */
export default function VoiceInput({onTranscript,disabled=false}){
  const [active,setActive]=useState(false);
  const [message,setMessage]=useState('');
  const recognition=useRef(null);
  const onTranscriptRef=useRef(onTranscript);
  onTranscriptRef.current=onTranscript;
  useEffect(()=>()=>{try{recognition.current?.abort()}catch{}},[]);
  function handleClick(){
    if(active){recognition.current?.stop();return}
    const API=window.SpeechRecognition||window.webkitSpeechRecognition;
    if(!API){setMessage('مرورگر شما از تشخیص گفتار پشتیبانی نمی‌کند. از Chrome یا Edge به‌روز استفاده کنید یا نام خودرو را بنویسید.');return}
    if(!window.isSecureContext){setMessage('برای استفاده از میکروفن، اتصال HTTPS لازم است.');return}
    try{
      const speech=new API();recognition.current=speech;
      speech.lang='fa-IR';speech.continuous=false;speech.interimResults=false;speech.maxAlternatives=1;
      let heard=false;
      speech.onresult=e=>{
        const text=String(e.results?.[0]?.[0]?.transcript||'').trim().replace(/[،,.!?]+$/g,'');
        if(text){heard=true;setMessage('تشخیص داده شد: '+text);onTranscriptRef.current?.(text)}
      };
      speech.onerror=e=>{
        setMessage(e.error==='not-allowed'||e.error==='service-not-allowed'?'دسترسی میکروفن مسدود است؛ مجوز میکروفن سایت را فعال کنید.':
          e.error==='no-speech'?'صدایی تشخیص داده نشد؛ دوباره صحبت کنید.':
          e.error==='network'?'سرویس تشخیص گفتار مرورگر در دسترس نیست؛ نام خودرو را تایپ کنید.':
          e.error==='audio-capture'?'میکروفن پیدا نشد؛ دستگاه ورودی را بررسی کنید.':'خطای میکروفن: '+e.error);
      };
      speech.onend=()=>{setActive(false);recognition.current=null;if(!heard)setMessage(v=>v||'دوباره روی میکروفن بزنید.')};
      setMessage('نام خودرو را بگویید؛ مثلاً «فیدلیتی پرایم»');setActive(true);speech.start();
    }catch{setActive(false);setMessage('میکروفن راه‌اندازی نشد. دسترسی مرورگر را بررسی کنید.')}
  }
  return <div className="voice-search-control">
    <button className={'voice-trigger '+(active?'voice-active':'')} type="button" onClick={handleClick} disabled={disabled}
      aria-label={active?'پایان شنیدن صدای خودرو':'گفتن نام خودرو با میکروفن'} aria-pressed={active}
      title={active?'پایان ضبط صدا':'نام خودرو را بگویید'}>
      <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="1.8"
        strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <rect x="9" y="2" width="6" height="12" rx="3"/>
        <path d="M5 10a7 7 0 0 0 14 0M12 17v5M8 22h8"/>
      </svg>
    </button>
    {message&&<span className="voice-status" role="status">{message}</span>}
  </div>;
}
