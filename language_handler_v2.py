# language_handler_v2.py - Multi-language support (9 languages)
SUPPORTED_LANGUAGES = {
    'hi': {'name': 'हिंदी (Hindi)', 'code': 'hi'},
    'en': {'name': 'English', 'code': 'en'},
    'mr': {'name': 'मराठी (Marathi)', 'code': 'mr'},
    'ta': {'name': 'தமிழ் (Tamil)', 'code': 'ta'},
    'te': {'name': 'తెలుగు (Telugu)', 'code': 'te'},
    'bn': {'name': 'বাংলা (Bengali)', 'code': 'bn'},
    'gu': {'name': 'ગુજરાતી (Gujarati)', 'code': 'gu'},
    'kn': {'name': 'ಕನ್ನಡ (Kannada)', 'code': 'kn'},
    'pa': {'name': 'ਪੰਜਾਬੀ (Punjabi)', 'code': 'pa'}
}

def get_language_menu():
    """Generate language selection menu"""
    menu = "🌐 *Select your preferred language:*\n\n"
    for i, (code, lang) in enumerate(SUPPORTED_LANGUAGES.items(), 1):
        menu += f"{i}. {lang['name']}\n"
    menu += "\nReply with the number (1-9)"
    return menu

def parse_language_choice(choice_text):
    """Parse user's language choice"""
    try:
        choice = int(choice_text.strip())
        if 1 <= choice <= len(SUPPORTED_LANGUAGES):
            lang_code = list(SUPPORTED_LANGUAGES.keys())[choice - 1]
            return lang_code
    except (ValueError, IndexError) as e:
        print(f"Warning: Invalid language choice '{choice_text}': {e}")
    return None

def get_language_name(code):
    """Get language display name"""
    try:
        return SUPPORTED_LANGUAGES.get(code, {}).get('name', 'Hindi')
    except Exception as e:
        print(f"Warning: get_language_name failed for code '{code}': {e}")
        return 'Hindi'

def get_summary_instructions(language_code):
    """Get language-specific summary instructions"""
    try:
        instructions = {
            'hi': "कृपया केवल हिंदी भाषा में मीटिंग का सारांश प्रदान करें। अन्य किसी भाषा का उपयोग न करें।",
            'en': "Please provide the meeting summary ONLY in English language. Do not use any other language.",
            'mr': "कृपया फक्त मराठी भाषेत मीटिंगचा सारांश द्या. इतर कोणत्याही भाषेचा वापर करू नका.",
            'ta': "தயவுசெய்து தமிழ் மொழியில் மட்டுமே கூட்டத்தின் சுருக்கத்தை வழங்கவும். வேறு எந்த மொழியையும் பயன்படுத்த வேண்டாம்.",
            'te': "దయచేసి తెలుగు భాషలో మాత్రమే సమావేశ సారాంశం అందించండి. ఇతర భాషలను ఉపయోగించవద్దు.",
            'bn': "অনুগ্রহ করে শুধুমাত্র বাংলা ভাষায় মিটিং এর সারসংক্ষেপ প্রদান করুন। অন্য কোনো ভাষা ব্যবহার করবেন না।",
            'gu': "કૃપા કરીને ફક્ત ગુજરાતી ભાષામાં જ મીટિંગનો સારાંશ આપો. અન્ય કોઈ ભાષાનો ઉપયોગ કરશો નહીં.",
            'kn': "ದಯವಿಟ್ಟು ಕನ್ನಡ ಭಾಷೆಯಲ್ಲಿ ಮಾತ್ರ ಸಭೆಯ ಸಾರಾಂಶವನ್ನು ಒದಗಿಸಿ. ಬೇರೆ ಯಾವುದೇ ಭಾಷೆಯನ್ನು ಬಳಸಬೇಡಿ.",
            'pa': "ਕਿਰਪਾ ਕਰਕੇ ਸਿਰਫ਼ ਪੰਜਾਬੀ ਭਾਸ਼ਾ ਵਿੱਚ ਹੀ ਮੀਟਿੰਗ ਦਾ ਸਾਰ ਪ੍ਰਦਾਨ ਕਰੋ। ਕੋਈ ਹੋਰ ਭਾਸ਼ਾ ਦੀ ਵਰਤੋਂ ਨਾ ਕਰੋ।"
        }
        return instructions.get(language_code, instructions['hi'])
    except Exception as e:
        print(f"Warning: get_summary_instructions failed for language '{language_code}': {e}")
        return "Please provide the meeting summary."
