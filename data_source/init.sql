-- Script combiné pour l'initialisation complète et la correction de la structure de la base de données
-- IMPORTANT: Toutes les données sont SYNTHÉTIQUES et à des fins de démonstration uniquement.

-- Désactiver les messages NOTICE pour réduire le bruit dans les logs
SET client_min_messages TO WARNING;

-- ============== PARTIE 1: CRÉATION DES TABLES PRINCIPALES ==============

-- Création des tables métier si elles n'existent pas
CREATE TABLE IF NOT EXISTS customers (
    customer_id SERIAL PRIMARY KEY,
    name VARCHAR(100), -- Nom synthétique
    last_activity_days INT,
    complaints_count INT,
    feedback_text TEXT, -- Feedback synthétique
    consent_given BOOLEAN DEFAULT TRUE, -- Indicateur de consentement pour la démo de gouvernance
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
COMMENT ON TABLE customers IS 'Table contenant les informations clients (synthétiques).';
COMMENT ON COLUMN customers.consent_given IS 'Indicateur de consentement du client (synthétique) pour l''analyse de feedback par IA.';

CREATE TABLE IF NOT EXISTS feedback_analysis (
    analysis_id SERIAL PRIMARY KEY,
    customer_id INT REFERENCES customers(customer_id) UNIQUE, -- Une seule analyse par client pour ce POC
    feedback_summary TEXT,
    sentiment VARCHAR(50), -- Ex: Positive, Negative, Neutral, Mixed
    key_topics TEXT,       -- Ex: "Fees, Mobile App Interface"
    analyzed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
COMMENT ON TABLE feedback_analysis IS 'Résultats de l''analyse NLP (via Groq) du feedback client.';

CREATE TABLE IF NOT EXISTS predictions (
    prediction_id SERIAL PRIMARY KEY,
    customer_id INT REFERENCES customers(customer_id) UNIQUE, -- Une seule prédiction par client pour ce POC
    churn_probability FLOAT CHECK (churn_probability >= 0 AND churn_probability <= 1), -- Probabilité entre 0 et 1
    predicted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
COMMENT ON TABLE predictions IS 'Résultats de prédiction de désabonnement du modèle ML.';
COMMENT ON COLUMN predictions.churn_probability IS 'Probabilité que le client quitte la banque (0=reste, 1=part).';

CREATE TABLE IF NOT EXISTS actions (
    action_id SERIAL PRIMARY KEY,
    customer_id INT REFERENCES customers(customer_id) UNIQUE, -- Une seule action par client pour ce POC
    segment VARCHAR(50), -- Ex: Low Risk, Medium Risk, High Risk
    recommended_action TEXT, -- Action générée par Groq
    processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
COMMENT ON TABLE actions IS 'Actions de rétention recommandées par l''agent IA.';
COMMENT ON COLUMN actions.segment IS 'Segment de risque basé sur la probabilité de désabonnement.';
COMMENT ON COLUMN actions.recommended_action IS 'Texte de l''action de rétention suggérée par le LLM.';

-- ======= Table d'audit pour la gouvernance =======
CREATE TABLE IF NOT EXISTS audit_log (
    log_id SERIAL PRIMARY KEY,
    log_timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP, -- Horodatage précis avec fuseau horaire
    agent_name VARCHAR(50) NOT NULL,        -- Nom de l'agent ('nlp', 'prediction', 'action')
    event_type VARCHAR(100) NOT NULL,       -- Type d'événement ('CONSENT_CHECK', 'ANONYMIZE_START', 'GROQ_CALL_END', etc.)
    status VARCHAR(20) DEFAULT 'INFO',      -- Statut ('INFO', 'SUCCESS', 'FAILURE', 'WARNING', 'ERROR')
    customer_id INT NULL,                   -- ID client associé (optionnel)
    details TEXT NULL                       -- Détails supplémentaires (message, durée, etc.)
);
COMMENT ON TABLE audit_log IS 'Trace des événements importants exécutés par les agents IA pour l''audit et la gouvernance.';
COMMENT ON COLUMN audit_log.event_type IS 'Catégorie de l''événement journalisé (ex. appel API, vérification, sauvegarde DB).';
COMMENT ON COLUMN audit_log.status IS 'Résultat de l''événement (succès, échec, info, etc.).';
COMMENT ON COLUMN audit_log.details IS 'Informations contextuelles supplémentaires pour l''événement.';

-- Index pour améliorer les requêtes sur la table d'audit
CREATE INDEX IF NOT EXISTS idx_audit_log_timestamp ON audit_log(log_timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_audit_log_event_type ON audit_log(event_type);
CREATE INDEX IF NOT EXISTS idx_audit_log_agent_name ON audit_log(agent_name);
-- Fin de la Table d'audit

-- ============== PARTIE 2: CORRECTIONS POUR LES AGENTS ==============

-- 1. Créer la table customer_feedback si elle n'existe pas
CREATE TABLE IF NOT EXISTS customer_feedback (
    feedback_id SERIAL PRIMARY KEY,
    customer_id INT REFERENCES customers(customer_id),
    feedback_text TEXT,
    submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT unique_customer_feedback UNIQUE (customer_id)
);
COMMENT ON TABLE customer_feedback IS 'Table contenant les feedbacks clients migrés depuis la table customers.';

-- 2. Transférer les données de feedback depuis customers vers customer_feedback
INSERT INTO customer_feedback (customer_id, feedback_text, submitted_at)
SELECT customer_id, feedback_text, created_at
FROM customers
WHERE feedback_text IS NOT NULL
ON CONFLICT (customer_id) DO NOTHING;

-- 3. Vérifier la structure de la table audit_log et ajouter la colonne timestamp si nécessaire
DO $$
BEGIN
    -- Vérifier si la colonne 'timestamp' n'existe pas, et si 'log_timestamp' existe
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                  WHERE table_name = 'audit_log' AND column_name = 'timestamp')
       AND EXISTS (SELECT 1 FROM information_schema.columns 
                  WHERE table_name = 'audit_log' AND column_name = 'log_timestamp')
    THEN
        -- Ajouter une colonne timestamp qui est un alias de log_timestamp
        EXECUTE 'ALTER TABLE audit_log ADD COLUMN "timestamp" TIMESTAMP DEFAULT CURRENT_TIMESTAMP';
        
        -- Mettre à jour les valeurs existantes
        EXECUTE 'UPDATE audit_log SET "timestamp" = log_timestamp';
    END IF;
END $$;

-- 4. Pour aider à débugger: Insérer une entrée dans feedback_analysis pour voir si ça corrige l'agent prediction
INSERT INTO feedback_analysis (customer_id, feedback_summary, sentiment, key_topics)
SELECT 
    cf.customer_id,
    'Analyse initiale automatique: ' || SUBSTRING(cf.feedback_text, 1, 50) || '...',
    CASE 
        WHEN c.complaints_count >= 3 THEN 'Negative'
        WHEN c.complaints_count >= 1 THEN 'Neutral'
        ELSE 'Positive'
    END AS sentiment,
    CASE 
        WHEN cf.feedback_text LIKE '%fee%' OR cf.feedback_text LIKE '%cost%' OR cf.feedback_text LIKE '%charge%' THEN 'Fees'
        WHEN cf.feedback_text LIKE '%app%' OR cf.feedback_text LIKE '%online%' OR cf.feedback_text LIKE '%mobile%' THEN 'Digital Banking'
        WHEN cf.feedback_text LIKE '%service%' OR cf.feedback_text LIKE '%support%' OR cf.feedback_text LIKE '%help%' THEN 'Customer Service'
        ELSE 'General Banking'
    END AS key_topics
FROM customer_feedback cf
JOIN customers c ON cf.customer_id = c.customer_id
LEFT JOIN feedback_analysis fa ON cf.customer_id = fa.customer_id
WHERE fa.customer_id IS NULL
AND cf.feedback_text IS NOT NULL
AND c.consent_given = TRUE  -- Respecter le consentement client
LIMIT 20;  -- Limiter à 20 enregistrements pour cette opération initiale

-- 5. Ajout d'index pour améliorer les performances
CREATE INDEX IF NOT EXISTS idx_customer_feedback_customer_id ON customer_feedback(customer_id);
CREATE INDEX IF NOT EXISTS idx_feedback_analysis_customer_id ON feedback_analysis(customer_id);
CREATE INDEX IF NOT EXISTS idx_predictions_customer_id ON predictions(customer_id);
CREATE INDEX IF NOT EXISTS idx_actions_customer_id ON actions(customer_id);
CREATE INDEX IF NOT EXISTS idx_audit_log_customer_id ON audit_log(customer_id);

-- ============== PARTIE 3: INSERTION DE DONNÉES SYNTHÉTIQUES ==============

-- Insertion de données clients SYNTHÉTIQUES si la table est vide
-- Utilise une structure qui évite les doublons si le script est exécuté plusieurs fois
DO $$
DECLARE
    -- Tableaux de prénoms et noms synthétiques pour la génération de données
    prenoms TEXT[] := ARRAY['Jean', 'Marie', 'Pierre', 'Sophie', 'Thomas', 'Isabelle', 'François', 'Emilie', 
                            'Nicolas', 'Nathalie', 'Michel', 'Claire', 'Philippe', 'Laura', 'André', 'Caroline', 
                            'Paul', 'Julie', 'Jacques', 'Emma', 'Lucas', 'Léa', 'Antoine', 'Camille', 'Julien', 
                            'Sarah', 'David', 'Aurélie', 'Marc', 'Céline', 'Alexandre', 'Elodie', 'Eric', 'Chloé', 
                            'Patrick', 'Valérie', 'Christophe', 'Sandrine', 'Sébastien', 'Laure', 'Guillaume', 
                            'Anne', 'Benoît', 'Catherine', 'Olivier', 'Stéphanie', 'Vincent', 'Mélanie', 'Daniel', 'Hélène',
                            'Robert', 'Mathilde', 'Louis', 'Amélie', 'Bernard', 'Charlotte', 'Henri', 'Agathe',
                            'Martin', 'Audrey', 'Laurent', 'Lucie', 'Sylvain', 'Sabrina', 'Richard', 'Nadia',
                            'Simon', 'Margaux', 'Fabien', 'Eva', 'Claude', 'Brigitte', 'Gérard', 'Pascale'];
    
    noms TEXT[] := ARRAY['Martin', 'Bernard', 'Dubois', 'Thomas', 'Robert', 'Richard', 'Petit', 'Durand', 
                         'Leroy', 'Moreau', 'Simon', 'Laurent', 'Lefebvre', 'Michel', 'Garcia', 'David', 
                         'Bertrand', 'Roux', 'Vincent', 'Fournier', 'Morel', 'Girard', 'Andre', 'Lefevre', 
                         'Mercier', 'Dupont', 'Lambert', 'Bonnet', 'Francois', 'Martinez', 'Legrand', 'Garnier', 
                         'Faure', 'Rousseau', 'Blanc', 'Guerin', 'Muller', 'Henry', 'Roussel', 'Nicolas', 
                         'Perrin', 'Morin', 'Mathieu', 'Clement', 'Gauthier', 'Dumont', 'Lopez', 'Fontaine', 
                         'Chevalier', 'Robin', 'Brun', 'Roy', 'Lemaire', 'Picard', 'Gaillard', 'Renard',
                         'Schmitt', 'Baron', 'Fabre', 'Marchand', 'Gillet', 'Schneider', 'Breton', 'Prevost',
                         'Millet', 'Perrot', 'Colin', 'Chevallier', 'Charpentier', 'Meyer', 'Lemoine', 'Masson'];
    
    -- Tableaux de feedbacks synthétiques - Version étendue avec plus de variété
    feedbacks_positifs TEXT[] := ARRAY[
        'Very satisfied with customer service. Excellent responsiveness!',
        'Intuitive and efficient mobile app. I can do all my operations without difficulty.',
        'The advisors are really attentive and professional.',
        'Excellent experience with this bank for 3 years now.',
        'The rates offered are competitive, I recommend this bank.',
        'I appreciate the simplicity of daily operations.',
        'The online service is available 24/7, which is convenient.',
        'No issues with my bank card, everything works perfectly.',
        'Account opening was quick and without excessive paperwork.',
        'My advisor Mrs. Dupont is very attentive to my needs.',
        'The interest rates on savings accounts are among the best in the market.',
        'Amazing customer service! They helped me resolve a payment issue in minutes.',
        'The mobile app fingerprint login makes banking so much more convenient and secure.',
        'I like how they send notifications for all transactions - makes me feel secure.',
        'Their investment advice has been spot on. My portfolio has grown steadily.',
        'So happy they offer free international transfers. Saves me a lot of money.',
        'The credit card reward program is excellent, I''ve earned back significant amounts.',
        'Love the budgeting tools in the app. Really helps me keep track of spending.',
        'Their mortgage rates were the best I could find anywhere.',
        'They found an error in my account and fixed it proactively - very impressed!',
        'Been with them for 15 years and never had any reason to complain.',
        'The savings plan they recommended has grown impressively over the last two years.',
        'Impressed by how quickly they processed my loan application - just 24 hours!',
        'Great experience with their currency exchange service. Very fair rates compared to others.',
        'Their customer service team went above and beyond when I lost my card abroad.'
    ];
    
    feedbacks_neutres TEXT[] := ARRAY[
        'Correct service but nothing exceptional.',
        'The mobile app could be improved in terms of navigation.',
        'Standard timeframes for international transfers.',
        'I haven''t had any major problems so far.',
        'Fees are average compared to other banks.',
        'Phone waiting time is acceptable.',
        'Website interface is a bit dated but functional.',
        'No particular issues with my account.',
        'Bank details difficult to find in customer portal.',
        'Basic service that meets minimum expectations.',
        'ATM network is adequate but could be more extensive.',
        'Customer service response time is average - not bad, not great.',
        'Interest rates are in line with the market, nothing special.',
        'App works fine most of the time but crashes occasionally.',
        'Branch hours are standard, would be nice if they stayed open later.',
        'Their mortgage process was straightforward but took longer than expected.',
        'Statement format is clear enough but could use modernization.',
        'Had to visit a branch twice to complete what should have been a simple process.',
        'Fee structure is transparent but not particularly competitive.',
        'The queue system at branches works but wait times vary considerably.',
        'No complaints about my credit card, but no special benefits either.',
        'Investment options are adequate but limited compared to specialized firms.',
        'The online chat support is useful but not always available.',
        'Account management is simple enough once you figure out their system.',
        'Foreign exchange rates are neither the best nor the worst I''ve seen.'
    ];
    
    feedbacks_negatifs TEXT[] := ARRAY[
        'Unacceptable delays for transfers! More than 5 days for a simple transfer.',
        'Impossible to reach customer service at number 0123456789. Endless waiting.',
        'Hidden fees of €35 withdrawn without warning. I''m going to change banks!',
        'App crashes regularly. Urgent update needed.',
        'My advisor never responds to my emails. I feel neglected.',
        'Error on my account statement not corrected for 2 months despite my complaints.',
        'Fee conditions changed without notice. It''s unacceptable!',
        'Incompetent customer service, I get different information with each call.',
        'Account closure extremely complicated, they''re making me go in circles.',
        'Overdraft refused even though I''ve been a customer for 10 years. I am very disappointed.',
        'Their security measures are a joke! My account was hacked twice this year.',
        'Terrible customer service - waited 45 minutes on the phone and then got disconnected.',
        'Five unauthorized charges on my account and they refuse to investigate properly.',
        'The interest rate they advertised was not what I actually received. Feels like fraud.',
        'Branch staff were rude and unhelpful when I needed assistance with a lost card.',
        'Mobile app constantly logs me out and I have to reset my password almost weekly.',
        'They charged me maintenance fees on what was supposed to be a free account!',
        'I submitted all required documents for a loan and they still denied it without explanation.',
        'Tried to get a mortgage through them - absolute nightmare of paperwork and delays.',
        'Been trying to close my account for three months and they keep finding excuses.',
        'ATM charged me €6 for a withdrawal even though they claim "free withdrawals worldwide".',
        'They lost my important documents twice and now I need to resubmit everything.',
        'My personal data was shared with marketing partners despite me explicitly opting out.',
        'Worst banking experience of my life. Moving all my accounts as soon as possible.',
        'They froze my account for "suspicious activity" which was just me traveling abroad - despite me notifying them in advance.'
    ];
    
    -- Catégories de feedback plus spécialisées pour plus de variété
    feedbacks_about_investments TEXT[] := ARRAY[
        'Very pleased with the investment advice. My portfolio has grown 12% this year.',
        'The robo-advisor service offers a good balance of risk and return for my profile.',
        'Disappointed with the limited ETF selection compared to specialized brokers.',
        'Financial advisor made excellent recommendations for my retirement planning.',
        'Not impressed with their mutual fund performance. High fees for mediocre returns.',
        'Their stock trading platform is too basic for my needs. Commission fees are high too.',
        'Very responsive investment team. They helped me rebalance my portfolio efficiently.',
        'The wealth management service is overpriced for what you actually get.'
    ];
    
    feedbacks_about_mortgage TEXT[] := ARRAY[
        'Mortgage approval was quick and the rate was better than competitors.',
        'The home loan process was transparent, but required too many documents.',
        'Frustrated with all the delays in processing my mortgage application.',
        'They found a great fixed-rate mortgage solution for my situation.',
        'Unhappy with how they handled my mortgage refinancing. Lost documents twice.',
        'Their mortgage advisor was knowledgeable and found me a better rate than I expected.',
        'Mortgage terms weren''t properly explained. Found hidden fees after signing.',
        'The online mortgage calculator was helpful but the actual offer was higher interest.'
    ];
    
    feedbacks_about_cards TEXT[] := ARRAY[
        'Love their premium credit card benefits. The travel insurance saved me on my last trip.',
        'The contactless card functionality works smoothly everywhere I shop.',
        'Credit card rewards program is disappointing compared to competitor banks.',
        'Had my card blocked while traveling despite notifying them beforehand.',
        'The metal card design is stylish and has impressed my clients.',
        'Card replacement took nearly 3 weeks. Left me without access to funds.',
        'The spending categories on my monthly statement make budgeting easy.',
        'International transaction fees are much higher than they advertised.'
    ];
    
    -- Variables pour la génération aléatoire
    i INTEGER;
    nom_complet TEXT;
    last_activity INTEGER;
    complaints INTEGER;
    feedback TEXT;
    consent BOOLEAN;
    feedback_type TEXT;
    feedback_category TEXT;
    all_feedback_count INTEGER;
BEGIN
    -- Vérifier si la table est vide avant d'insérer
    IF NOT EXISTS (SELECT 1 FROM customers) THEN
        -- Insérer les données originales pour la compatibilité
        INSERT INTO customers (name, last_activity_days, complaints_count, feedback_text, consent_given) VALUES
        ('Alice Dubois (Synth)', 5, 0, 'Fast and efficient service, I am very satisfied with my bank. The mobile application is clear.', TRUE),
        ('Bob Martin (Synth)', 95, 3, 'The international transfer took 10 days! Customer service at 0123456789 was unreachable. I am thinking of switching to BankPro.', TRUE),
        ('Charlie Durand (Synth)', 30, 1, 'Mobile app interface not clear for finding bank details. My advisor Mr. Dupont is responsive.', TRUE),
        ('Diana Lefevre (Synth)', 150, 5, 'Fees of 50eur charged without notice on my account 987654321! This is unacceptable, I will close my account tomorrow. Address: 1 rue de la Paix', TRUE),
        ('Ethan Moreau (Synth)', 15, 0, NULL, TRUE), -- Pas de feedback
        ('Fiona Petit (Synth)', 210, 4, 'I sent an email to service.client@banque.fr for a complaint about fees, never got a response. Very disappointed.', FALSE), -- !! CONSENTEMENT REFUSÉ !!
        ('Gabriel Leroy (Synth)', 60, 0, 'Everything works well, no issues.', TRUE);
        
        -- Ajouter quelques cas de test spécifiques
        INSERT INTO customers (name, last_activity_days, complaints_count, feedback_text, consent_given) VALUES
        ('Jennifer Smith (Synth)', 2, 0, 'The new rewards program is excellent! I''ve earned $120 in cashback this month alone. Your mobile app is intuitive and secure.', TRUE),
        ('Michael Johnson (Synth)', 180, 7, 'This is the worst bank I''ve ever used. Hidden fees everywhere, impossible to reach support, and your app crashes constantly. I''m closing all accounts immediately.', TRUE),
        ('Emma Williams (Synth)', 45, 2, 'Your mortgage rates are competitive but the application process is unnecessarily complicated. My advisor Ms. Hughes was helpful though.', TRUE),
        ('John Brown (Synth)', 8, 0, 'I appreciate the investment advice from your wealth management team. My portfolio is up 15% this year!', TRUE),
        ('Patricia Davis (Synth)', 300, 5, 'After 12 years with your bank, I''m leaving. The service quality has declined dramatically and your fees are no longer competitive.', FALSE),
        ('David Wilson (Synth)', 90, 3, 'The credit card rewards are average. Your competitor offers double points on similar spending categories.', TRUE),
        ('Elizabeth Thompson (Synth)', 1, 0, 'Just opened my account yesterday. The process was smooth and your staff was extremely helpful.', TRUE),
        ('Robert Garcia (Synth)', 120, 4, 'It took three attempts and two branch visits to get my address updated in your system. Your processes need serious improvement.', TRUE);
        
        -- Générer 50 clients synthétiques supplémentaires (pour réduire la taille du script)
        FOR i IN 1..50 LOOP
            -- Générer un nom complet aléatoire
            nom_complet := prenoms[1 + floor(random() * array_length(prenoms, 1))] || ' ' || 
                          noms[1 + floor(random() * array_length(noms, 1))] || ' (Synth)';
            
            -- Générer dernière activité (entre 1 et 365 jours)
            last_activity := 1 + floor(random() * 365);
            
            -- Générer nombre de plaintes (entre 0 et 7)
            complaints := floor(random() * 8);
            
            -- Déterminer le type de feedback en fonction de l'activité et des plaintes
            -- Pour créer une corrélation entre activité, plaintes et sentiment du feedback
            IF last_activity > 180 OR complaints >= 3 THEN
                feedback_type := 'negatif';
            ELSIF last_activity > 60 OR complaints >= 1 THEN
                feedback_type := 'neutre';
            ELSE
                feedback_type := 'positif';
            END IF;
            
            -- Sélectionner aléatoirement une catégorie de feedback spécialisée (20% des cas)
            IF random() < 0.2 THEN
                -- Choisir une catégorie spécialisée
                CASE floor(random() * 3)
                    WHEN 0 THEN feedback_category := 'investment';
                    WHEN 1 THEN feedback_category := 'mortgage';
                    ELSE feedback_category := 'card';
                END CASE;
            ELSE
                feedback_category := 'general';
            END IF;
            
            -- Sélectionner un feedback aléatoire basé sur le type et la catégorie
            IF feedback_category = 'investment' THEN
                all_feedback_count := array_length(feedbacks_about_investments, 1);
                
                -- Pour les investissements, utiliser une sélection pondérée basée sur le sentiment
                IF feedback_type = 'negatif' THEN
                    -- Utiliser plus de feedback négatif (indices 5-7)
                    feedback := feedbacks_about_investments[5 + floor(random() * 3)];
                ELSIF feedback_type = 'neutre' THEN
                    -- Utiliser plus de feedback neutre (indices 2, 3, 5)
                    CASE floor(random() * 3)
                        WHEN 0 THEN feedback := feedbacks_about_investments[2];
                        WHEN 1 THEN feedback := feedbacks_about_investments[3];
                        ELSE feedback := feedbacks_about_investments[5];
                    END CASE;
                ELSE
                    -- Utiliser plus de feedback positif (indices 0, 1, 3, 6)
                    CASE floor(random() * 4)
                        WHEN 0 THEN feedback := feedbacks_about_investments[0];
                        WHEN 1 THEN feedback := feedbacks_about_investments[1];
                        WHEN 2 THEN feedback := feedbacks_about_investments[3];
                        ELSE feedback := feedbacks_about_investments[6];
                    END CASE;
                END IF;
            ELSIF feedback_category = 'mortgage' THEN
                all_feedback_count := array_length(feedbacks_about_mortgage, 1);
                
                -- Pour les hypothèques, utiliser une sélection pondérée basée sur le sentiment
                IF feedback_type = 'negatif' THEN
                    -- Utiliser plus de feedback négatif (indices 2, 4, 6, 7)
                    CASE floor(random() * 4)
                        WHEN 0 THEN feedback := feedbacks_about_mortgage[2];
                        WHEN 1 THEN feedback := feedbacks_about_mortgage[4];
                        WHEN 2 THEN feedback := feedbacks_about_mortgage[6];
                        ELSE feedback := feedbacks_about_mortgage[7];
                    END CASE;
                ELSIF feedback_type = 'neutre' THEN
                    -- Utiliser plus de feedback neutre (indices 1, 7)
                    IF random() < 0.5 THEN
                        feedback := feedbacks_about_mortgage[1];
                    ELSE
                        feedback := feedbacks_about_mortgage[7];
                    END IF;
                ELSE
                    -- Utiliser plus de feedback positif (indices 0, 3, 5)
                    CASE floor(random() * 3)
                        WHEN 0 THEN feedback := feedbacks_about_mortgage[0];
                        WHEN 1 THEN feedback := feedbacks_about_mortgage[3];
                        ELSE feedback := feedbacks_about_mortgage[5];
                    END CASE;
                END IF;
            ELSIF feedback_category = 'card' THEN
                all_feedback_count := array_length(feedbacks_about_cards, 1);
                
                -- Pour les cartes, utiliser une sélection pondérée basée sur le sentiment
                IF feedback_type = 'negatif' THEN
                    -- Utiliser plus de feedback négatif (indices 2, 3, 5, 7)
                    CASE floor(random() * 4)
                        WHEN 0 THEN feedback := feedbacks_about_cards[2];
                        WHEN 1 THEN feedback := feedbacks_about_cards[3];
                        WHEN 2 THEN feedback := feedbacks_about_cards[5];
                        ELSE feedback := feedbacks_about_cards[7];
                    END CASE;
                ELSIF feedback_type = 'neutre' THEN
                    -- Utiliser plus de feedback neutre (indices 2, 7)
                    IF random() < 0.5 THEN
                        feedback := feedbacks_about_cards[2];
                    ELSE
                        feedback := feedbacks_about_cards[7];
                    END IF;
                ELSE
                    -- Utiliser plus de feedback positif (indices 0, 1, 4, 6)
                    CASE floor(random() * 4)
                        WHEN 0 THEN feedback := feedbacks_about_cards[0];
                        WHEN 1 THEN feedback := feedbacks_about_cards[1];
                        WHEN 2 THEN feedback := feedbacks_about_cards[4];
                        ELSE feedback := feedbacks_about_cards[6];
                    END CASE;
                END IF;
            ELSE
                -- Feedback général
                IF feedback_type = 'negatif' THEN
                    feedback := feedbacks_negatifs[1 + floor(random() * array_length(feedbacks_negatifs, 1))];
                ELSIF feedback_type = 'neutre' THEN
                    feedback := feedbacks_neutres[1 + floor(random() * array_length(feedbacks_neutres, 1))];
                ELSE
                    feedback := feedbacks_positifs[1 + floor(random() * array_length(feedbacks_positifs, 1))];
                END IF;
            END IF;
            
            -- 10% des clients n'ont pas de feedback
            IF random() < 0.1 THEN
                feedback := NULL;
            END IF;
            
            -- 15% des clients n'ont pas donné leur consentement
            consent := random() >= 0.15;
            
            -- Insérer le client dans la table
            INSERT INTO customers (
                name, 
                last_activity_days, 
                complaints_count, 
                feedback_text, 
                consent_given
            ) VALUES (
                nom_complet,
                last_activity,
                complaints,
                feedback,
                consent
            );
        END LOOP;
        
        -- Assurer que les données de feedback sont également dans la table customer_feedback
        INSERT INTO customer_feedback (customer_id, feedback_text, submitted_at)
        SELECT customer_id, feedback_text, created_at
        FROM customers
        WHERE feedback_text IS NOT NULL
        ON CONFLICT (customer_id) DO NOTHING;
        
        RAISE NOTICE 'Données clients synthétiques insérées (65 clients au total pour cette version abrégée).';
    ELSE
        RAISE NOTICE 'La table customers contient déjà des données.';
    END IF;
END $$;

-- ============== PARTIE 4: STATISTIQUES ET FINALISATION ==============

-- 6. Statistiques pour vérification
SELECT 'Table customers' AS table_name, count(*) AS row_count FROM customers
UNION ALL
SELECT 'Table customer_feedback' AS table_name, count(*) AS row_count FROM customer_feedback
UNION ALL
SELECT 'Table feedback_analysis' AS table_name, count(*) AS row_count FROM feedback_analysis
UNION ALL
SELECT 'Table predictions' AS table_name, count(*) AS row_count FROM predictions
UNION ALL
SELECT 'Table actions' AS table_name, count(*) AS row_count FROM actions
UNION ALL
SELECT 'Table audit_log' AS table_name, count(*) AS row_count FROM audit_log;

-- Réactiver les messages NOTICE si nécessaire
-- SET client_min_messages TO NOTICE;

-- Message final dans les logs Docker
SELECT 'Script d''initialisation et de correction complet exécuté avec succès. Base de données prête avec jeu de données synthétique.' AS status;